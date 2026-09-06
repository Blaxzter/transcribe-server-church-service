"""Stage 7: speaker diarization with pyannote community-1.

Chosen over NVIDIA NeMo Sortformer, which is architecturally capped at four
speakers - unusable for a service with a Pfarrer:in, Lektor:in, Kantor:in,
guests and the congregation. pyannote estimates the speaker count from the
audio with no ceiling.

Turns are masked to the stage-4 speech regions before being returned, so
diarization never claims a speaker was talking over the organ.
"""
from __future__ import annotations

import contextlib
import gc
import logging
from typing import Any, Callable

import numpy as np
import torch

from ..config import DIARIZATION_MODEL, HF_TOKEN, MAX_SPEAKERS, MIN_SPEAKERS, SAMPLE_RATE
from . import vad as vad_stage

log = logging.getLogger(__name__)

_MIN_TURN_S = 0.25


class _ProgressHook:
    """Adapter for pyannote's hook protocol - maps internal steps onto 0..1."""

    STEPS = ["segmentation", "embeddings", "clustering", "discrete_diarization"]

    def __init__(self, on_progress: Callable[[float], None] | None) -> None:
        self._on_progress = on_progress

    def __call__(self, step_name: str, step_artifact: Any = None, file: Any = None,
                 total: int | None = None, completed: int | None = None,
                 **_: Any) -> None:
        if not self._on_progress:
            return
        try:
            index = self.STEPS.index(step_name)
        except ValueError:
            return
        within = (completed / total) if (total and completed is not None) else 0.0
        self._on_progress((index + min(within, 1.0)) / len(self.STEPS))

    def __enter__(self) -> "_ProgressHook":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


_SAFE_GLOBALS_REGISTERED = False


def _allowlist_pyannote_globals() -> None:
    """Teach torch's safe unpickler about pyannote's own classes.

    torch 2.6 flipped `torch.load` to `weights_only=True`, and pyannote
    checkpoints carry dataclasses and enums that the safe unpickler refuses by
    default. Allowlisting the specific classes is the narrow fix.
    """
    global _SAFE_GLOBALS_REGISTERED
    if _SAFE_GLOBALS_REGISTERED:
        return
    _SAFE_GLOBALS_REGISTERED = True
    try:
        import torch.serialization as serialization
        from pyannote.audio.core.task import Problem, Resolution, Specifications

        serialization.add_safe_globals([Specifications, Problem, Resolution])
    except Exception:  # pragma: no cover - pyannote internals moved
        log.debug("could not allowlist pyannote globals", exc_info=True)


@contextlib.contextmanager
def _trusted_torch_load():
    """Restore pre-2.6 `torch.load` behaviour for one checkpoint load.

    The allowlist above covers the classes we know about; a version bump can
    introduce others. This is the fallback, deliberately scoped to a single call
    rather than set globally: it disables the safe unpickler, which is only
    acceptable because the checkpoint comes from the pinned pyannote repo the
    operator explicitly granted access to.
    """
    original = torch.load

    def patched(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original(*args, **kwargs)

    torch.load = patched
    try:
        yield
    finally:
        torch.load = original


def _from_pretrained():
    from pyannote.audio import Pipeline

    # pyannote 4 renamed use_auth_token -> token; support both so a version bump
    # does not take the server down.
    try:
        return Pipeline.from_pretrained(DIARIZATION_MODEL, token=HF_TOKEN)
    except TypeError:
        return Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=HF_TOKEN)


def _load_pipeline():
    _allowlist_pyannote_globals()
    try:
        return _from_pretrained()
    except Exception as exc:
        message = str(exc)
        if "weights_only" not in message and "WeightsUnpickler" not in message:
            raise
        log.warning("checkpoint needs the pre-2.6 torch.load behaviour; retrying")
        with _trusted_torch_load():
            return _from_pretrained()


def run(audio: np.ndarray, speech_regions: list[dict[str, float]], device: torch.device,
        on_progress: Callable[[float], None] | None = None,
        num_speakers: int | None = None) -> list[dict[str, Any]]:
    pipeline = _load_pipeline()
    if pipeline is None:
        raise RuntimeError(
            "Diarisierungsmodell konnte nicht geladen werden. Ist HF_TOKEN gesetzt und "
            "sind die Modellbedingungen auf huggingface.co akzeptiert?"
        )
    pipeline.to(device)

    waveform = torch.from_numpy(np.ascontiguousarray(audio)).float().unsqueeze(0)
    payload = {"waveform": waveform, "sample_rate": SAMPLE_RATE}

    constraints: dict[str, Any] = {}
    if num_speakers:
        constraints["num_speakers"] = int(num_speakers)
    else:
        constraints["min_speakers"] = MIN_SPEAKERS
        constraints["max_speakers"] = MAX_SPEAKERS

    try:
        with _ProgressHook(on_progress) as hook:
            try:
                output = pipeline(payload, hook=hook, **constraints)
            except TypeError:
                output = pipeline(payload, **constraints)
    finally:
        del pipeline
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    annotation = _exclusive(output)
    turns = [
        {"start": float(segment.start), "end": float(segment.end), "speaker": str(label)}
        for segment, _, label in annotation.itertracks(yield_label=True)
    ]
    turns = _mask(turns, speech_regions)

    speakers = sorted({t["speaker"] for t in turns})
    log.info("diarize: %d turns, %d speakers", len(turns), len(speakers))
    return turns


def _exclusive(output: Any):
    """Prefer the non-overlapping view.

    community-1 exposes `exclusive_speaker_diarization` specifically to make
    reconciliation with ASR timestamps straightforward - one speaker per instant,
    so word attribution is an interval lookup rather than an overlap heuristic.
    """
    for attribute in ("exclusive_speaker_diarization", "speaker_diarization"):
        annotation = getattr(output, attribute, None)
        if annotation is not None:
            return annotation
    return output  # pyannote 3.x returned a bare Annotation


def _mask(turns: list[dict[str, Any]],
          speech_regions: list[dict[str, float]]) -> list[dict[str, Any]]:
    if not speech_regions:
        return turns
    regions = vad_stage.merge_overlapping(list(speech_regions))
    masked: list[dict[str, Any]] = []
    for turn in turns:
        for region in regions:
            start = max(turn["start"], region["start"])
            end = min(turn["end"], region["end"])
            if end - start >= _MIN_TURN_S:
                masked.append({"start": round(start, 3), "end": round(end, 3),
                               "speaker": turn["speaker"]})
    masked.sort(key=lambda t: t["start"])

    # Stitch turns of the same speaker that the masking split by a short gap.
    stitched: list[dict[str, Any]] = []
    for turn in masked:
        if (stitched and stitched[-1]["speaker"] == turn["speaker"]
                and turn["start"] - stitched[-1]["end"] < 0.4):
            stitched[-1]["end"] = max(stitched[-1]["end"], turn["end"])
        else:
            stitched.append(turn)
    return stitched
