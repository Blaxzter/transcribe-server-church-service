"""German-specific Whisper hallucination filtering.

Whisper was trained on a great deal of subtitled video, so when it is handed
audio with little or no speech it falls back on the phrases that padded those
subtitles: broadcaster credits, "thanks for watching" outros, and subtitling
community sign-offs. On a church recording these appear over organ music and in
long silences.

Music detection removes most of the opportunity; this module catches the rest.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Matched against the whole (stripped, case-folded) segment text. These are
# phrases that are never legitimately said in a Gottesdienst.
_DENYLIST = [
    r"untertitel(ung)?\b.*\b(zdf|ard|wdr|swr|br|orf|srf|funk|amara)",
    r"untertitel\s+(von|im auftrag|der|erstellt)",
    r"untertitelung\s+aufgrund",
    r"amara\.org",
    r"\bcopyright\b.*\b(zdf|ard|wdr|swr|br|orf|srf)\b",
    # Covers "fürs", "für's", "für das" and the ue/oe transliterations, which
    # Whisper produces interchangeably.
    r"(vielen dank|danke)\s+(f(ü|ue|u)r)?\s*['’]?\s*(s|das)?\s*"
    r"(zuschauen|zusehen|zuh(ö|oe)ren)",
    r"bis zum n(ä|ae)chsten mal",
    r"abonniere?[nt]?\s+(den\s+)?kanal",
    r"mehr infos? (auf|unter)\s+www",
    r"^\W*(musik|music|applaus|applause|gesang)\W*$",
    r"^\W*\[?\s*(musik|music)\s*\]?\W*$",
    r"^\W*(untertitel|subtitles?)\W*$",
    r"^\W*(vielen dank|danke)\W*$",
    r"^\W*(amen)\W*$\s*(?=$)",  # only when it is the entire, isolated segment
]

_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _DENYLIST]

# A segment that is mostly one repeated fragment is a decoder loop, not speech.
_MIN_REPEAT_RUN = 4


def is_denylisted(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    # "Amen" alone is a real thing to say in a service, so it is only dropped
    # when it is also very short and unpunctuated - handled by the caller via
    # confidence. Keep the generic check cheap here.
    return any(pattern.search(stripped) for pattern in _PATTERNS[:-1])


def collapse_repetitions(text: str) -> str:
    """Collapse runs of an identical word or short phrase down to one occurrence.

    Whisper loops look like "und dann und dann und dann und dann ..."; a human
    repeating themselves twice is normal, four-plus times is a decoder failure.
    """
    words = text.split()
    if len(words) < _MIN_REPEAT_RUN:
        return text

    for size in (1, 2, 3, 4, 5):
        index = 0
        output: list[str] = []
        while index < len(words):
            phrase = words[index:index + size]
            if len(phrase) < size:
                output.extend(phrase)
                break
            repeats = 1
            probe = index + size
            while (probe + size <= len(words)
                   and [w.lower() for w in words[probe:probe + size]]
                   == [w.lower() for w in phrase]):
                repeats += 1
                probe += size
            if repeats >= _MIN_REPEAT_RUN:
                output.extend(phrase)
                index = probe
            else:
                output.extend(phrase)
                index += size
        words = output
    return " ".join(words)


def is_prompt_echo(text: str, prompt: str | None) -> bool:
    """True when a segment is really the initial prompt read back.

    Observed in testing: over a passage the model was unsure about, it emitted
    the liturgical vocabulary prompt verbatim, with a *high* avg_logprob - so no
    confidence threshold catches it. The prompt is disabled by default now, but
    anyone who re-enables one needs this backstop.
    """
    if not prompt:
        return False
    words = _tokenize(text)
    if len(words) < 4:
        return False
    prompt_words = set(_tokenize(prompt))
    if not prompt_words:
        return False
    shared = sum(1 for word in words if word in prompt_words)
    # Almost every word coming from the prompt is not a coincidence.
    return shared / len(words) >= 0.8


def _tokenize(text: str) -> list[str]:
    return [w for w in re.split(r"[^\w]+", text.lower()) if w]


def looks_like_loop(text: str) -> bool:
    """True when a segment is dominated by one repeated token."""
    words = [w.lower().strip(".,!?;:") for w in text.split()]
    if len(words) < 8:
        return False
    unique = len(set(words))
    return unique / len(words) < 0.25


def clean(segments: list[dict[str, Any]], *, log_prob_floor: float = -1.15,
          prompt: str | None = None
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split segments into (kept, dropped). Dropped ones are retained for debugging."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for segment in segments:
        text = (segment.get("text") or "").strip()
        reason = None

        if not text:
            reason = "empty"
        elif is_denylisted(text):
            reason = "denylist"
        elif is_prompt_echo(text, prompt):
            reason = "prompt-echo"
        elif looks_like_loop(text):
            reason = "repetition-loop"
        elif segment.get("avg_logprob") is not None and \
                segment["avg_logprob"] < log_prob_floor:
            reason = "low-confidence"

        if reason:
            dropped.append({**segment, "drop_reason": reason})
            continue

        collapsed = collapse_repetitions(text)
        if collapsed != text:
            segment = {**segment, "text": collapsed, "words": None}
        kept.append(segment)

    if dropped:
        counts: dict[str, int] = {}
        for item in dropped:
            counts[item["drop_reason"]] = counts.get(item["drop_reason"], 0) + 1
        log.info("hallucination filter dropped %d segments: %s", len(dropped), counts)
    return kept, dropped
