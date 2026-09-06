"""Stage 4: voice activity detection.

Deliberately uses the Silero VAD bundled with faster-whisper - the *same* VAD the
ASR stage gates on. Running one VAD for transcription and a different one for
diarization is the documented cause of boundary hallucinations in diarized
pipelines; sharing a single VAD removes that class of error entirely.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..config import (SAMPLE_RATE, VAD_MAX_SPEECH_S, VAD_MIN_SILENCE_MS,
                      VAD_MIN_SPEECH_MS, VAD_SPEECH_PAD_MS, VAD_THRESHOLD)

log = logging.getLogger(__name__)


def vad_options():
    """Build VadOptions, keeping only fields this faster-whisper version has.

    The dataclass has gained and lost fields across releases; passing an unknown
    one is a TypeError that would fail the whole job for no good reason.
    """
    import dataclasses

    from faster_whisper.vad import VadOptions

    wanted = {
        "threshold": VAD_THRESHOLD,
        "min_speech_duration_ms": VAD_MIN_SPEECH_MS,
        "max_speech_duration_s": VAD_MAX_SPEECH_S,
        "min_silence_duration_ms": VAD_MIN_SILENCE_MS,
        "speech_pad_ms": VAD_SPEECH_PAD_MS,
    }
    available = {field.name for field in dataclasses.fields(VadOptions)}
    unknown = set(wanted) - available
    if unknown:
        log.warning("faster-whisper VadOptions does not accept %s; ignoring", unknown)
    return VadOptions(**{k: v for k, v in wanted.items() if k in available})


def detect(audio: np.ndarray) -> list[dict[str, float]]:
    """Raw Silero speech regions in seconds, music included.

    This is what the ASR stage cuts its clips from: sung passages stay in so
    that music filtering happens in one place, merge, on tightened bounds.
    """
    from faster_whisper.vad import get_speech_timestamps

    chunks = get_speech_timestamps(audio, vad_options())
    return [{"start": c["start"] / SAMPLE_RATE, "end": c["end"] / SAMPLE_RATE}
            for c in chunks]


def run(audio: np.ndarray, music_regions: list[dict[str, Any]],
        detected: list[dict[str, float]] | None = None) -> list[dict[str, float]]:
    """Speech regions with music cut out - the anchor for diarization and merge.

    `detected` lets the pipeline run Silero once and share the result with the
    ASR stage.
    """
    speech = detected if detected is not None else detect(audio)
    speech = subtract(speech, music_regions)
    total = sum(s["end"] - s["start"] for s in speech)
    log.info("vad: %d speech regions, %.1f min of speech", len(speech), total / 60)
    return speech


def subtract(regions: list[dict[str, float]],
             cutouts: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Remove cutouts from regions, splitting where a cutout lands inside one."""
    if not cutouts:
        return regions
    blocked = merge_overlapping([{"start": c["start"], "end": c["end"]} for c in cutouts])
    result: list[dict[str, float]] = []
    for region in regions:
        pieces = [dict(region)]
        for cut in blocked:
            next_pieces: list[dict[str, float]] = []
            for piece in pieces:
                if cut["end"] <= piece["start"] or cut["start"] >= piece["end"]:
                    next_pieces.append(piece)
                    continue
                if cut["start"] > piece["start"]:
                    next_pieces.append({"start": piece["start"], "end": cut["start"]})
                if cut["end"] < piece["end"]:
                    next_pieces.append({"start": cut["end"], "end": piece["end"]})
            pieces = next_pieces
        result.extend(p for p in pieces if p["end"] - p["start"] > 0.1)
    return result


def merge_overlapping(regions: list[dict[str, float]]) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for region in sorted(regions, key=lambda r: r["start"]):
        if merged and region["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], region["end"])
        else:
            merged.append(dict(region))
    return merged


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def covered_fraction(start: float, end: float, regions: list[dict[str, Any]]) -> float:
    span = end - start
    if span <= 0:
        return 0.0
    return sum(overlap(start, end, r["start"], r["end"]) for r in regions) / span
