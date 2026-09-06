"""Stage 5: speech recognition with faster-whisper.

Model choice: German sits at a statistical tie across the current front-runners
(FLEURS German - Whisper large-v3 4.30% WER, Canary-1B-v2 4.40%, Voxtral-Mini
4.62%), so this picks on tooling and VRAM rather than accuracy. large-v3 at
int8_float16 is ~3 GB, which is what makes the rest of the pipeline fit in 8 GB.

The transcribe settings below are the anti-hallucination configuration; they
matter more for this recording type than the model choice does.
"""
from __future__ import annotations

import gc
import inspect
import logging
from typing import Any, Callable

import numpy as np
import torch

from .. import hallucinations
from ..config import (ASR_BATCH_SIZE, ASR_CLIP_MAX_GAP_S, ASR_CLIP_MIN_FILL,
                      ASR_COMPUTE_TYPE, ASR_MODEL, ASR_WINDOW_S, INITIAL_PROMPT,
                      LANGUAGE)
from . import merge as merge_stage
from . import vad as vad_stage

log = logging.getLogger(__name__)

# Anti-hallucination settings. The batched pipeline never conditions on previous
# text, which removes the single largest cause of repeat loops; the thresholds
# below catch what is left.
DECODE_OPTIONS: dict[str, Any] = {
    "language": LANGUAGE,
    "task": "transcribe",
    "beam_size": 5,
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "repetition_penalty": 1.05,
    "no_repeat_ngram_size": 0,
    "word_timestamps": True,
}
if INITIAL_PROMPT:
    # Off by default - see the note in config.py about prompt regurgitation.
    DECODE_OPTIONS["initial_prompt"] = INITIAL_PROMPT


def run(audio: np.ndarray, duration: float, device: torch.device,
        on_progress: Callable[[float], None] | None = None,
        speech_regions: list[dict[str, float]] | None = None) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    clips = plan_clips(speech_regions) if speech_regions else []
    if clips:
        log.info("asr: %d speech regions planned into %d clips", len(speech_regions), len(clips))

    # int8_float16 needs a GPU; on the CPU fallback path plain int8 is the only
    # sensible choice.
    on_gpu = device.type == "cuda"
    compute_type = ASR_COMPUTE_TYPE if on_gpu else "int8"
    model = WhisperModel(ASR_MODEL, device="cuda" if on_gpu else "cpu",
                         compute_type=compute_type)
    try:
        segments_iter, info = _transcribe(model, audio, clips)
        raw: list[dict[str, Any]] = []
        for segment in segments_iter:
            raw.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": (segment.text or "").strip(),
                "avg_logprob": getattr(segment, "avg_logprob", None),
                "no_speech_prob": getattr(segment, "no_speech_prob", None),
                "words": [
                    {"word": w.word, "start": float(w.start), "end": float(w.end),
                     "probability": float(getattr(w, "probability", 0.0) or 0.0)}
                    for w in (segment.words or [])
                    if w.start is not None and w.end is not None
                ] or None,
            })
            if on_progress and duration > 0:
                on_progress(min(float(segment.end) / duration, 1.0))
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    kept, dropped = hallucinations.clean(raw, prompt=INITIAL_PROMPT)

    # With planned clips a segment is a contiguous span of at most 30 s and its
    # timings are honest. On the fallback paths (no regions, an older
    # faster-whisper, the sequential model) the batched pipeline packs VAD
    # chunks across long musical gaps, so a segment's timestamps can span
    # thirteen minutes while its text is a single sentence spoken at the very
    # start. Correct that here, before anything downstream trusts a timespan:
    #   - alignment is quadratic in clip length, so a 13-minute "segment" takes
    #     that stage from 40 seconds to effectively forever;
    #   - the music-overlap check in merge would see a span covering a whole
    #     hymn and throw away real liturgy (it ate the Vaterunser in testing).
    # Music filtering itself deliberately happens in merge, not here.
    kept = [merge_stage.tighten_bounds(s) for s in kept]

    log.info("asr: %d segments, %d kept, %d dropped (language=%s p=%.2f)",
             len(raw), len(kept), len(dropped),
             getattr(info, "language", LANGUAGE),
             float(getattr(info, "language_probability", 0.0) or 0.0))

    return {
        "segments": kept,
        "dropped": dropped,
        "language": getattr(info, "language", LANGUAGE),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
    }


def _supported(function, options: dict[str, Any]) -> dict[str, Any]:
    """Drop options this faster-whisper version does not accept.

    The transcribe signatures differ between the batched and sequential paths
    and change across releases. Silently dropping an unsupported knob is much
    better than failing a 90-minute job on a TypeError.
    """
    try:
        accepted = set(inspect.signature(function).parameters)
    except (TypeError, ValueError):
        return options
    unknown = set(options) - accepted
    if unknown:
        log.debug("ignoring unsupported transcribe options: %s", sorted(unknown))
    return {k: v for k, v in options.items() if k in accepted}


def plan_clips(regions: list[dict[str, float]], *, window: float = ASR_WINDOW_S,
               max_gap: float = ASR_CLIP_MAX_GAP_S,
               min_fill: float = ASR_CLIP_MIN_FILL) -> list[dict[str, float]]:
    """Group speech regions into the clips Whisper is handed.

    Left to itself, faster-whisper's batched pipeline packs regions into a clip
    by summed speech duration and starts a new one when the next region no
    longer fits. That cuts wherever the arithmetic lands, which is regularly a
    second or two into a sentence - and Whisper reliably drops a short fragment
    hanging off the end of its window. On the 2026-08-27 service every fragment
    that went missing outside music was the last region of a packed clip.

    Here a clip is a contiguous span of the original audio, so the pauses in it
    are real and the word timings come out honest, and it ends at the widest
    pause among the regions that fit once the window is reasonably full. A
    pause longer than `max_gap` always ends a clip, which keeps long silences
    out of the window. Each region lands in exactly one clip; a lone region
    longer than the window is passed through and truncated by Whisper, which
    the VAD's own maximum speech duration prevents in practice.
    """
    clips: list[dict[str, float]] = []
    index, count = 0, len(regions)
    while index < count:
        start = regions[index]["start"]
        last = index
        natural_end = True
        while last + 1 < count:
            following = regions[last + 1]
            if following["end"] - start > window:
                natural_end = False
                break
            if following["start"] - regions[last]["end"] > max_gap:
                break
            last += 1

        cut = last
        if not natural_end:
            candidates = range(index, last + 1)
            filled = [k for k in candidates
                      if regions[k]["end"] - start >= min_fill * window]
            pause = lambda k: regions[k + 1]["start"] - regions[k]["end"]  # noqa: E731
            # Later on a tie, so the clip is as full as the pauses allow.
            cut = max(filled or list(candidates), key=lambda k: (pause(k), k))

        clips.append({"start": start, "end": regions[cut]["end"]})
        index = cut + 1
    return clips


def _transcribe(model, audio: np.ndarray, clips: list[dict[str, float]]):
    """Batched inference, falling back to sequential if the batched path fails.

    Batching is worth roughly 3x here, but it is also the newer code path; the
    fallback means a faster-whisper regression costs speed rather than breaking
    the server.
    """
    from faster_whisper import BatchedInferencePipeline

    vad_parameters = vad_stage.vad_options()
    base = {**DECODE_OPTIONS, "vad_filter": True, "vad_parameters": vad_parameters}

    try:
        batched = BatchedInferencePipeline(model=model)
        # Planned clips replace the pipeline's own VAD packing; without them
        # (no regions, or an older faster-whisper without clip_timestamps) it
        # falls back to packing for itself.
        planned = {**DECODE_OPTIONS, "clip_timestamps": clips} if clips else base
        options = _supported(batched.transcribe, {**planned, "batch_size": ASR_BATCH_SIZE})
        if clips and "clip_timestamps" not in options:
            options = _supported(batched.transcribe, {**base, "batch_size": ASR_BATCH_SIZE})
        return batched.transcribe(audio, **options)
    except Exception:
        log.warning("batched inference unavailable, falling back to sequential",
                    exc_info=True)

    # The sequential path *does* condition on previous text by default, which is
    # the single largest cause of repeat loops - turn it off explicitly.
    sequential = {**base,
                  "condition_on_previous_text": False,
                  "hallucination_silence_threshold": 2.0}
    return model.transcribe(audio, **_supported(model.transcribe, sequential))
