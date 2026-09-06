"""Stage 3: find the music and label it, instead of letting Whisper hallucinate over it.

Organ preludes, hymns and congregational singing are the single biggest source
of Whisper garbage in a Gottesdienst recording - it invents subtitle credits and
falls into repeat loops. Rather than transcribing them (Demucs-style vocal
separation was evaluated and rejected: it measurably *increases* Whisper
hallucination), these spans are detected with an AudioSet tagger and replaced by
markers such as [Orgelspiel] or [Gemeindegesang].
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import torch

from ..config import (MUSIC_BATCH, MUSIC_HOP_S, MUSIC_MARKERS, MUSIC_MERGE_GAP_S,
                      MUSIC_MIN_DURATION_S, MUSIC_MODEL, MUSIC_OVER_SPEECH,
                      MUSIC_SPEECH_VETO, MUSIC_THRESHOLD, MUSIC_WINDOW_S,
                      SAMPLE_RATE, SPEECH_LABELS)

log = logging.getLogger(__name__)


def _label_indices(id2label: dict[int, str], wanted: tuple[str, ...]) -> list[int]:
    lookup = {name.strip().lower(): idx for idx, name in id2label.items()}
    found = [lookup[name.strip().lower()] for name in wanted if name.strip().lower() in lookup]
    missing = [n for n in wanted if n.strip().lower() not in lookup]
    if missing:
        log.debug("AudioSet labels not present in model: %s", missing)
    return found


def run(audio: np.ndarray, device: torch.device,
        on_progress: Callable[[float], None] | None = None
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (regions, windows).

    The per-window scores are returned as well as the regions because
    MUSIC_THRESHOLD and MUSIC_OVER_SPEECH can only really be set against a real
    recording: dump the windows over a passage you know is a hymn and read the
    numbers off. The pipeline writes them to music_windows.json.
    """
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    extractor = AutoFeatureExtractor.from_pretrained(MUSIC_MODEL)
    model = AutoModelForAudioClassification.from_pretrained(MUSIC_MODEL).to(device).eval()

    id2label = {int(k): v for k, v in model.config.id2label.items()}
    marker_indices = [(marker, _label_indices(id2label, labels))
                      for marker, labels in MUSIC_MARKERS]
    marker_indices = [(m, idx) for m, idx in marker_indices if idx]
    speech_indices = _label_indices(id2label, SPEECH_LABELS)
    if not marker_indices:
        raise RuntimeError("music model exposes none of the expected AudioSet labels")

    window = int(MUSIC_WINDOW_S * SAMPLE_RATE)
    hop = int(MUSIC_HOP_S * SAMPLE_RATE)
    starts = list(range(0, max(len(audio) - window // 2, 1), hop))
    duration = len(audio) / SAMPLE_RATE
    # Half the overlap: the offset from a window's start to its "core" span.
    margin = (MUSIC_WINDOW_S - MUSIC_HOP_S) / 2

    windows: list[dict[str, Any]] = []
    try:
        with torch.inference_mode():
            for batch_start in range(0, len(starts), MUSIC_BATCH):
                batch = starts[batch_start:batch_start + MUSIC_BATCH]
                clips = []
                for offset in batch:
                    clip = audio[offset:offset + window]
                    if len(clip) < window:
                        clip = np.pad(clip, (0, window - len(clip)))
                    clips.append(clip)

                inputs = extractor(clips, sampling_rate=SAMPLE_RATE, return_tensors="pt")
                inputs = {k: v.to(device) for k, v in inputs.items()}
                probabilities = torch.sigmoid(model(**inputs).logits).float().cpu().numpy()

                for offset, probs in zip(batch, probabilities):
                    best_marker, best_score = None, 0.0
                    for marker, indices in marker_indices:
                        score = float(probs[indices].max())
                        if score > best_score:
                            best_marker, best_score = marker, score
                    speech = float(probs[speech_indices].max()) if speech_indices else 0.0

                    # A window is 10 s wide but only advances 5 s, so its verdict
                    # is attributed to the middle 5 s. Without this a region
                    # starts up to 5 s before the music does and swallows the
                    # speech immediately preceding a hymn. The first and last
                    # windows extend to the edges of the recording.
                    window_start = offset / SAMPLE_RATE
                    is_first = offset == starts[0]
                    is_last = offset == starts[-1]
                    core_start = 0.0 if is_first else window_start + margin
                    core_end = duration if is_last else window_start + margin + MUSIC_HOP_S

                    windows.append({
                        "start": round(core_start, 3),
                        "end": round(min(core_end, duration), 3),
                        "marker": best_marker,
                        "music": best_score,
                        "speech": speech,
                        "is_music": bool(
                            best_marker
                            and best_score >= MUSIC_THRESHOLD
                            and best_score >= speech * MUSIC_OVER_SPEECH
                            # Confident speech always wins, however loud the
                            # music: this is the fade-out of a hymn with someone
                            # already talking over it.
                            and speech < MUSIC_SPEECH_VETO
                        ),
                    })

                if on_progress:
                    on_progress(min((batch_start + len(batch)) / max(len(starts), 1), 1.0))
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    regions = _to_regions(windows)
    log.info("music: %d of %d windows tagged, %d regions",
             sum(1 for w in windows if w["is_music"]), len(windows), len(regions))
    return regions, windows


def _to_regions(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Windows to merged, de-fragmented regions.

    Windows overlap (10 s wide, 5 s hop), so a region grows from the first music
    window and extends while music windows keep arriving. Short gaps are bridged
    and short regions dropped, so one loud cough does not split a hymn into
    three fragments.
    """
    grown: list[dict[str, Any]] = []
    for window in windows:
        if not window["is_music"]:
            continue
        if grown and window["start"] - grown[-1]["end"] <= MUSIC_MERGE_GAP_S:
            current = grown[-1]
            current["end"] = max(current["end"], window["end"])
            current["votes"].append((window["marker"], window["music"]))
        else:
            grown.append({"start": window["start"], "end": window["end"],
                          "votes": [(window["marker"], window["music"])]})

    finished: list[dict[str, Any]] = []
    for region in grown:
        if region["end"] - region["start"] < MUSIC_MIN_DURATION_S:
            continue
        # The marker for the whole region is the family with the highest summed
        # confidence, so a hymn that opens with organ still reads as singing.
        totals: dict[str, float] = {}
        for marker, score in region["votes"]:
            totals[marker] = totals.get(marker, 0.0) + score
        finished.append({
            "start": round(region["start"], 3),
            "end": round(region["end"], 3),
            "marker": max(totals, key=totals.__getitem__),
            "confidence": round(max(score for _, score in region["votes"]), 3),
        })
    return finished
