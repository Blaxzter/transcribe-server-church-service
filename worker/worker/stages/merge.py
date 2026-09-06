"""Stage 8: assemble the transcript document.

Takes ASR segments, diarization turns and music regions and produces the single
JSON document the UI reads and edits. The interesting part is splitting an ASR
segment when a speaker changes mid-segment: Whisper decides segment boundaries
from prosody and has no idea a different person started talking.
"""
from __future__ import annotations

import bisect
import logging
from typing import Any

from . import vad as vad_stage

log = logging.getLogger(__name__)

# Colours are assigned in order of first appearance. Chosen to stay legible on
# both light and dark backgrounds.
PALETTE = [
    "#2563eb", "#db2777", "#059669", "#d97706",
    "#7c3aed", "#0891b2", "#dc2626", "#65a30d",
    "#c026d3", "#0d9488", "#e11d48", "#4f46e5",
]

# A speaker run shorter than this is absorbed into its neighbour rather than
# becoming its own segment - it is almost always a diarization wobble on a
# single word, not a real interjection.
_MIN_RUN_WORDS = 2
_MIN_RUN_SECONDS = 0.6
_NEAREST_TURN_TOLERANCE = 0.5
# A music region cut below this by overlapping speech is noise, not a passage.
_MIN_MUSIC_AFTER_TRIM_S = 2.5

# A segment this deeply inside detected music is the model narrating a hymn.
# Only meaningful once bounds have been tightened to the real words.
_MUSIC_OVERLAP_DROP = 0.5

# Segment length targets. Whisper's own segments run ~30 s, which reads as a
# wall of text; these cut at sentence ends into something followable.
_MAX_SEGMENT_SECONDS = 18.0
_MIN_SPLIT_SECONDS = 6.0
_HARD_SPLIT_SECONDS = 30.0


class SpeakerIndex:
    """Point lookup over non-overlapping diarization turns."""

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self.turns = sorted(turns, key=lambda t: t["start"])
        self._starts = [t["start"] for t in self.turns]

    def at(self, moment: float) -> str | None:
        if not self.turns:
            return None
        index = bisect.bisect_right(self._starts, moment) - 1
        if index >= 0 and self.turns[index]["end"] >= moment:
            return self.turns[index]["speaker"]
        # Just outside a turn: snap to whichever neighbour is close enough.
        best, best_distance = None, _NEAREST_TURN_TOLERANCE
        for candidate in self.turns[max(index, 0):min(index + 2, len(self.turns))]:
            distance = min(abs(candidate["start"] - moment), abs(candidate["end"] - moment))
            if distance < best_distance:
                best, best_distance = candidate["speaker"], distance
        return best

    def dominant(self, start: float, end: float) -> str | None:
        totals: dict[str, float] = {}
        for turn in self.turns:
            if turn["end"] <= start:
                continue
            if turn["start"] >= end:
                break
            seconds = vad_stage.overlap(start, end, turn["start"], turn["end"])
            if seconds > 0:
                totals[turn["speaker"]] = totals.get(turn["speaker"], 0.0) + seconds
        return max(totals, key=totals.__getitem__) if totals else None


def run(*, job_id: str, duration: float, language: str,
        asr_segments: list[dict[str, Any]], turns: list[dict[str, Any]],
        music_regions: list[dict[str, Any]]) -> dict[str, Any]:
    index = SpeakerIndex(turns)

    # Order matters. Bounds must be corrected before anything judges a segment
    # by its timespan, and long segments must be broken up before speakers are
    # assigned, so a speaker change lands on a sentence boundary where possible.
    segments = [tighten_bounds(s) for s in asr_segments]
    segments, swallowed = _drop_inside_music(segments, music_regions)
    segments = [piece for s in segments for piece in _split_long(s)]

    pieces: list[dict[str, Any]] = []
    for segment in segments:
        pieces.extend(_split_by_speaker(segment, index))

    for region in _music_without_speech(music_regions, pieces):
        pieces.append({
            "type": "music",
            "start": region["start"],
            "end": region["end"],
            "marker": region["marker"],
            "text": region["marker"],
            "confidence": region.get("confidence"),
        })

    pieces.sort(key=lambda p: (p["start"], p["end"]))
    for number, piece in enumerate(pieces):
        piece["id"] = f"s{number}"

    speakers = _speaker_map(pieces)
    log.info("merge: %d segments (%d music), %d speakers, %d dropped inside music",
             len(pieces), sum(1 for p in pieces if p["type"] == "music"),
             len(speakers), len(swallowed))

    return {
        "version": 1,
        "job_id": job_id,
        "duration": round(duration, 3),
        "language": language,
        "speakers": speakers,
        "segments": pieces,
    }


def tighten_bounds(segment: dict[str, Any]) -> dict[str, Any]:
    """Replace a segment's bounds with the extent of its actual words.

    faster-whisper's batched pipeline merges VAD chunks across silence, so on a
    church recording a segment can claim to span thirteen minutes when its text
    is one sentence spoken at the start and the rest is organ music. Every
    downstream decision - music overlap, speaker lookup, click-to-seek - is
    wrong if it trusts those bounds.
    """
    words = segment.get("words")
    if not words:
        return segment
    first, last = words[0], words[-1]
    if last["end"] <= first["start"]:
        return segment
    return {**segment,
            "start": round(float(first["start"]), 3),
            "end": round(float(last["end"]), 3)}


def _drop_inside_music(segments: list[dict[str, Any]],
                       music_regions: list[dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Discard transcription that sits inside detected music.

    This is Whisper narrating a hymn. It only runs on tightened bounds - applied
    to raw batched-pipeline bounds it deletes real speech, because a segment
    whose span happens to cover a hymn is not the same as a segment *of* a hymn.
    """
    if not music_regions:
        return segments, []
    kept, dropped = [], []
    for segment in segments:
        covered = vad_stage.covered_fraction(segment["start"], segment["end"],
                                             music_regions)
        if covered > _MUSIC_OVERLAP_DROP:
            dropped.append({**segment, "drop_reason": "inside-music"})
        else:
            kept.append(segment)
    if dropped:
        log.info("merge: dropped %d segments sitting inside music", len(dropped))
    return kept, dropped


def _split_long(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Break an over-long segment at sentence boundaries.

    Whisper emits roughly 30-second segments, which makes a transcript a wall of
    text and click-to-seek useless. Word timings let us cut on real sentence
    ends, so each paragraph is something a reader can follow and edit.
    """
    words = segment.get("words")
    if not words or segment["end"] - segment["start"] <= _MAX_SEGMENT_SECONDS:
        return [segment]

    pieces: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        current.append(word)
        span = word["end"] - current[0]["start"]
        ends_sentence = word["word"].strip().endswith((".", "!", "?", "…", ":"))
        if span >= _MIN_SPLIT_SECONDS and ends_sentence:
            pieces.append(current)
            current = []
        elif span >= _HARD_SPLIT_SECONDS:
            # No punctuation in sight - cut anyway rather than emit a monster.
            pieces.append(current)
            current = []
    if current:
        if pieces and len(current) < 3:
            pieces[-1].extend(current)   # a trailing fragment belongs with the previous
        else:
            pieces.append(current)

    if len(pieces) <= 1:
        return [segment]

    result = []
    for index, group in enumerate(pieces):
        result.append({
            **segment,
            # Preserve the outer edges so the timeline keeps no holes.
            "start": segment["start"] if index == 0 else round(group[0]["start"], 3),
            "end": segment["end"] if index == len(pieces) - 1 else round(group[-1]["end"], 3),
            "text": " ".join(w["word"].strip() for w in group).strip(),
            "words": group,
        })
    return result


def _music_without_speech(music_regions: list[dict[str, Any]],
                          speech: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clip music regions back so they never sit on top of transcribed speech.

    Music detection classifies 10-second windows, so a region's edges run a few
    seconds past the actual music: a window that is only 40% organ still scores
    ~0.77. Left alone the transcript shows "[Orgelspiel] 0:00-0:12" overlapping a
    sentence starting at 0:09.

    Speech wins these overlaps. Anything that survived to here is a passage the
    ASR was confident about and that was not already mostly inside music, so it
    is better evidence of where the music actually stopped than the window
    boundary is. A region cut down to a sliver is dropped entirely.
    """
    if not music_regions or not speech:
        return music_regions

    spoken = vad_stage.merge_overlapping(
        [{"start": s["start"], "end": s["end"]} for s in speech]
    )
    trimmed: list[dict[str, Any]] = []
    for region in music_regions:
        for piece in vad_stage.subtract([{"start": region["start"], "end": region["end"]}],
                                        spoken):
            if piece["end"] - piece["start"] >= _MIN_MUSIC_AFTER_TRIM_S:
                trimmed.append({**region,
                                "start": round(piece["start"], 3),
                                "end": round(piece["end"], 3)})
    return trimmed


def _split_by_speaker(segment: dict[str, Any], index: SpeakerIndex) -> list[dict[str, Any]]:
    words = segment.get("words")
    start, end = float(segment["start"]), float(segment["end"])

    if not words:
        return [{
            "type": "speech",
            "start": round(start, 3),
            "end": round(end, 3),
            "speaker": index.dominant(start, end),
            "text": segment["text"],
            "words": None,
        }]

    # Group consecutive words that belong to the same speaker.
    runs: list[dict[str, Any]] = []
    for word in words:
        midpoint = (word["start"] + word["end"]) / 2
        speaker = index.at(midpoint)
        if runs and runs[-1]["speaker"] == speaker:
            runs[-1]["words"].append(word)
        else:
            runs.append({"speaker": speaker, "words": [word]})

    runs = _absorb_short_runs(runs)

    result: list[dict[str, Any]] = []
    for run_index, current in enumerate(runs):
        run_words = current["words"]
        text = " ".join(w["word"].strip() for w in run_words).strip()
        if not text:
            continue
        result.append({
            "type": "speech",
            # Keep the original segment bounds at the outer edges so the
            # timeline has no gaps between consecutive segments.
            "start": round(start if run_index == 0 else run_words[0]["start"], 3),
            "end": round(end if run_index == len(runs) - 1 else run_words[-1]["end"], 3),
            "speaker": current["speaker"],
            "text": text,
            "words": run_words,
        })
    return result or [{
        "type": "speech", "start": round(start, 3), "end": round(end, 3),
        "speaker": index.dominant(start, end), "text": segment["text"], "words": None,
    }]


def _absorb_short_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold away runs too short to be a real turn."""
    if len(runs) <= 1:
        return runs
    result: list[dict[str, Any]] = []
    for current in runs:
        words = current["words"]
        span = words[-1]["end"] - words[0]["start"]
        too_short = len(words) < _MIN_RUN_WORDS and span < _MIN_RUN_SECONDS
        if too_short and result:
            result[-1]["words"].extend(words)
        elif result and result[-1]["speaker"] == current["speaker"]:
            result[-1]["words"].extend(words)
        else:
            result.append(current)
    return result


def _speaker_map(pieces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    order: list[str] = []
    for piece in pieces:
        speaker = piece.get("speaker")
        if speaker and speaker not in order:
            order.append(speaker)
    return {
        speaker: {
            "label": f"Sprecher {position + 1}",
            "color": PALETTE[position % len(PALETTE)],
            "auto": True,
        }
        for position, speaker in enumerate(order)
    }
