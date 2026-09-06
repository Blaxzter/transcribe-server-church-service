"""Extract hymn references from a transcript.

Measured across 122 real services, hymn numbers are always announced as digits
next to a cue word - "Choral 71", "Lied Nummer 254", "im Johannischen Gesangbuch
Nr. 177". Not one was spelled out, which is why this is rules-based rather than
another LLM pass: it keeps exact timestamps for click-to-seek, works when the
summary model is switched off, is testable, and can backfill the whole imported
archive without touching the GPU.

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


def numbers_from_title(title: str) -> list[int]:
    """Hymn numbers encoded in the archive's file-naming convention.

    88 of 122 titles carry them as a dash-joined group, e.g.
    "2026-08-30 C.Schermutzki 116-122-245". Used to check the extractor against
    what a human wrote down at the time.
    """
    # Skip a leading ISO date, whose own dashes would otherwise match.
    without_date = re.sub(r"^\s*\d{4}-\d{2}-\d{2}", " ", title)
    numbers: list[int] = []
    for group in re.finditer(r"\b\d{1,3}(?:\s*-\s*\d{1,3})+\b", without_date):
        for part in re.findall(r"\d{1,3}", group.group(0)):
            value = int(part)
            if MIN_NUMBER <= value <= MAX_NUMBER:
                numbers.append(value)
    return numbers


def collect(document: dict[str, Any], title: str | None = None) -> list[dict[str, Any]]:
    """Every hymn of a service, from both sources that know about them.

    The transcript is the trustworthy source: 103 hymns across 54 services,
    each with the moment it was announced.

    Filenames are the second source and a weaker one. 88 of 122 carry a
    dash-joined number group, but the operator does not vouch for them being
    right, and they carry no timing - so they are merged in for coverage,
    marked `source: "title"`, and rendered without a play control. Drop the
    title argument to show only what the recording itself says.
    """
    spoken = {entry["number"]: {**entry, "source": "transcript"}
              for entry in extract(document)}
    for number in numbers_from_title(title or ""):
        if number in spoken:
            spoken[number]["source"] = "both"
        else:
            spoken[number] = {"number": number, "at": None, "segment_id": None,
                              "context": None, "mentions": 0, "source": "title"}
    # Timestamped first, in playback order; the rest by number.
    return sorted(spoken.values(),
                  key=lambda h: (h["at"] is None, h["at"] or 0, h["number"]))
