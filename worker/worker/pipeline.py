"""Pipeline orchestration.

Stages run strictly one after another and each releases its model before the
next loads. That is not an optimisation - with 8 GB of VRAM, Whisper large-v3,
the alignment model, pyannote and the summarisation LLM simply cannot be
resident at the same time.

Every stage writes its raw output next to the audio, so a failure late in the
pipeline can be diagnosed without re-running the expensive parts.
"""
from __future__ import annotations

import gc
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .config import LLM_ENABLED, SAMPLE_RATE, job_dir
from .reporting import Reporter
from .stages import align, asr, diarize, merge, music, normalize, peaks, summarize, vad

log = logging.getLogger(__name__)


def device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    log.warning("no CUDA device visible - falling back to CPU, this will be very slow")
    return torch.device("cpu")


def write_json(path: Path, payload: Any) -> None:
    """Atomic write: a crash mid-write must not leave a truncated JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def find_original(directory: Path) -> Path:
    matches = sorted(directory.glob("original.*"))
    if not matches:
        raise FileNotFoundError(f"Keine Originaldatei in {directory}")
    return matches[0]


def process(job_id: str) -> dict[str, Any]:
    directory = job_dir(job_id)
    original = find_original(directory)
    compute_device = device()

    skip = set() if LLM_ENABLED else {"summarize"}
    reporter = Reporter(job_id, skip=skip)
    reporter.start()

    try:
        # -- 1/2: decode + waveform ---------------------------------------
        wav_path = directory / "audio.wav"
        opus_path = directory / "audio.opus"
        peaks_path = directory / "peaks.json"

        if wav_path.exists() and opus_path.exists() and peaks_path.exists():
            # A retry: the CPU stages are deterministic, so reuse them.
            duration = normalize.probe_duration(wav_path)
            log.info("job %s: reusing existing normalised audio", job_id)
        else:
            reporter.stage("normalize")
            _, _, duration = normalize.run(original, directory, reporter.progress)
            reporter.stage("peaks")
            peaks.run(wav_path, directory, duration)

        # Decode once and hand the same array to every stage that needs audio.
        audio = _load_audio(wav_path)

        # -- 3: music ------------------------------------------------------
        reporter.stage("music")
        music_regions, music_windows = music.run(audio, compute_device, reporter.progress)
        write_json(directory / "music.json", music_regions)
        # Per-window scores: the only practical way to tune MUSIC_THRESHOLD and
        # MUSIC_OVER_SPEECH against a real recording.
        write_json(directory / "music_windows.json", music_windows)

        # -- 4: VAD --------------------------------------------------------
        reporter.stage("vad")
        speech_regions = vad.run(audio, music_regions)
        write_json(directory / "vad.json", speech_regions)
        if not speech_regions:
            raise RuntimeError("In der Aufnahme wurde keine Sprache gefunden.")

        # -- 5: ASR --------------------------------------------------------
        reporter.stage("asr")
        transcription = asr.run(audio, duration, compute_device, reporter.progress)
        write_json(directory / "asr.json", transcription)
        segments = transcription["segments"]

        # -- 6: alignment (refinement; failures fall back to Whisper timings)
        reporter.stage("align")
        segments = align.run(audio, segments, compute_device, reporter.progress)

        # -- 7: diarization ------------------------------------------------
        reporter.stage("diarize")
        turns = diarize.run(audio, speech_regions, compute_device, reporter.progress)
        write_json(directory / "diarization.json", turns)

        del audio
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # -- 8: merge ------------------------------------------------------
        reporter.stage("merge")
        document = merge.run(
            job_id=job_id,
            duration=duration,
            language=transcription.get("language", "de"),
            asr_segments=segments,
            turns=turns,
            music_regions=music_regions,
        )
        write_json(directory / "transcript.json", document)

        # -- 9: summary (optional, never fatal) ----------------------------
        if LLM_ENABLED:
            reporter.stage("summarize")
            try:
                summary = summarize.run(document, reporter.progress)
                write_json(directory / "summary.json", summary)
                document["summary"] = summary.get("summary")
                document["outline"] = summary.get("outline")
                write_json(directory / "transcript.json", document)
            except summarize.SummaryUnavailable as exc:
                log.warning("job %s: summary skipped: %s", job_id, exc)
            except Exception:
                log.exception("job %s: summary failed", job_id)

        speaker_count = len(document.get("speakers", {}))
        reporter.finished(duration_s=round(duration, 2), speaker_count=speaker_count)
        log.info("job %s finished: %.1f min, %d speakers, %d segments",
                 job_id, duration / 60, speaker_count, len(document["segments"]))
        return {"duration_s": duration, "speaker_count": speaker_count}

    except Exception as exc:
        log.exception("job %s failed", job_id)
        reporter.failed(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        reporter.close()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _load_audio(wav_path: Path) -> np.ndarray:
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(wav_path), sampling_rate=SAMPLE_RATE)
    return np.ascontiguousarray(audio, dtype=np.float32)
