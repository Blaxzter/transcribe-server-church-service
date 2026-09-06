"""Extract hymn references from a transcript.

Measured across 122 real services, hymn numbers are always announced as digits
next to a cue word - "Choral 71", "Lied Nummer 254", "im Johannischen Gesangbuch
Nr. 177". Not one was spelled out, which is why this is rules-based rather than
another LLM pass: it keeps exact timestamps for click-to-seek, works when the
summary model is switched off, is testable, and needs no reprocessing.

Only what the recording actually says is reported. An earlier version also
mined hymn numbers out of the filename, which covered more services but could
not be verified and had no timing, so those entries could not be clicked and
could not be trusted. They are gone: every hymn shown now has a moment in the
audio behind it.

The trap is verse numbers. "Die Strophen 1 bis 4 und 6" and "Nummer 144, Strophe
1 bis 4" sit right next to hymn announcements and must never be mistaken for
hymns, or every service gains a hymn "1".
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# Johannisches Gesangbuch numbering. Anything outside this is a year, a Bible
# verse or a stray digit, not a hymn.
MIN_NUMBER = 1
MAX_NUMBER = 999

_CUE = r"(?:choral|lied|gesangbuch|gesang)"
_ORDINAL = r"(?:nummer|nr\.?|no\.?)"

# "Choral 71", "Lied Nummer 254", "Gesangbuch Nr. 177"
_WITH_CUE = re.compile(
    rf"\b{_CUE}\b[\s,:–-]*(?:{_ORDINAL}[\s,:]*)?(\d{{1,3}})\b", re.IGNORECASE)
# A bare "Nummer 144" with no hymn word, which the announcements also use.
_BARE_ORDINAL = re.compile(rf"\b{_ORDINAL}[\s,:]*(\d{{1,3}})\b", re.IGNORECASE)

# "Choral aus unserem Gesangbuch, die 71" - the number trails the cue by a few
# words. Requiring an article or ordinal directly in front of it keeps this from
# swallowing any stray number that happens to follow a hymn word.
_TRAILING = re.compile(
    rf"\b{_CUE}\b[^.!?]{{0,60}}?\b(?:die|der|das|den|{_ORDINAL})\s+(\d{{1,3}})\b",
    re.IGNORECASE)

# Verse talk. Checked against the text immediately before a match.
_VERSE_BEFORE = re.compile(r"stroph[en]*\s*$", re.IGNORECASE)
# "Strophen 1 bis 4 und 6" - only the numbers hanging directly off the cue are
# verses. Consuming the rest of the sentence instead, as this once did, meant a
# single "Strophen" earlier on hid a real announcement later in the same
# sentence: "alle vier Strophen und nach der Predigt den Choral Nummer 154".
_VERSE_RUN = re.compile(
    r"\bstroph[en]*\b(?:\s*(?:\d{1,3}|bis|und|oder|[,–-]))*", re.IGNORECASE)


def _verse_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _VERSE_RUN.finditer(text)]


def _inside(position: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(lo <= position < hi for lo, hi in spans)


# How much of the preceding segment to read as context. Whisper splits mid
# announcement - "…den ersten Choral von unserem Liederzettel singen," / "die
# 440, Ich bin getauft" - so a per-segment scan alone never sees the cue.
LOOKBEHIND_CHARS = 90


def find_in_text(text: str) -> list[int]:
    """Hymn numbers announced in a piece of text, in order of appearance."""
    return [number for number, _ in find_with_positions(text)]


def find_with_positions(text: str) -> list[tuple[int, int]]:
    """(number, index of its digits) so callers can tell which segment it is in."""
    verses = _verse_spans(text)
    found: list[tuple[int, int]] = []
    seen_at: set[int] = set()

    for pattern in (_WITH_CUE, _TRAILING, _BARE_ORDINAL):
        for match in pattern.finditer(text):
            # Deduplicate on where the digits are, not where the match began:
            # "Lied Nummer 27" is found by both patterns at the same number, and
            # keying on the match start would report it twice.
            if match.start(1) in seen_at:
                continue
            # "... die Strophen 1 bis 4 und 6" - verse numbers, not hymns.
            if _inside(match.start(1), verses):
                continue
            if _VERSE_BEFORE.search(text[:match.start(1)]):
                continue
            number = int(match.group(1))
            if MIN_NUMBER <= number <= MAX_NUMBER:
                seen_at.add(match.start(1))
                found.append((number, match.start(1)))
    return sorted(found, key=lambda pair: pair[1])


def _around(text: str, number: int, width: int) -> str:
    """A snippet centred on the announcement, not the start of the segment.

    A segment can run for half a minute before the number is said, so taking its
    opening words would cut off the very thing the snippet is meant to show.
    """
    match = re.search(rf"\b{number}\b", text)
    if not match:
        return text[:width].strip()
    half = width // 2
    start = max(0, match.start() - half)
    end = min(len(text), match.end() + half)
    snippet = text[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def extract(document: dict[str, Any], *, context_chars: int = 90
            ) -> list[dict[str, Any]]:
    """Hymn references with the timestamp they were announced at.

    Returns one entry per distinct number, keeping its first mention, so the UI
    can list the hymns of a service and jump to where each was announced.
    """
    by_number: dict[int, dict[str, Any]] = {}
    previous = ""
    for segment in document.get("segments", []):
        if segment.get("type") == "music":
            previous = ""      # music breaks the sentence; do not read across it
            continue
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        # Prepend the tail of the previous segment so an announcement split
        # across the boundary is still seen, then keep only the numbers whose
        # digits fall inside this segment.
        lead = previous[-LOOKBEHIND_CHARS:]
        offset = len(lead) + 1 if lead else 0
        combined = f"{lead} {text}" if lead else text
        previous = text
        for number, position in find_with_positions(combined):
            if position < offset:
                continue
            if number in by_number:
                by_number[number]["mentions"] += 1
                continue
            by_number[number] = {
                "number": number,
                "at": round(float(segment.get("start") or 0.0), 2),
                "segment_id": segment.get("id"),
                "context": _around(text, number, context_chars),
                "mentions": 1,
            }
    return sorted(by_number.values(), key=lambda h: h["at"])
