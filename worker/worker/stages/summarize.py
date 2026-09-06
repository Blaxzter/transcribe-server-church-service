"""Stage 9: optional German summary and outline via a local LLM.

Runs last and on its own, because the summarisation model needs ~5 GB and the
8 GB budget has no room for it alongside anything else. Ollama is configured
with OLLAMA_KEEP_ALIVE=0 so it releases VRAM the moment a request returns.

Map-reduce rather than one long prompt: a 90-minute service is roughly 25k
tokens, and Ollama defaults to a 4096-token context window. Summarising chunks
and then summarising the summaries keeps every request comfortably inside it.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import httpx

from ..config import LLM_CHUNK_CHARS, LLM_MODEL, LLM_NUM_CTX, OLLAMA_URL

log = logging.getLogger(__name__)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_REQUEST_TIMEOUT = httpx.Timeout(600.0, connect=15.0)

CHUNK_PROMPT = """Du fasst einen Abschnitt eines deutschen Gottesdienstes zusammen.

Gib eine sachliche Zusammenfassung in 3 bis 5 Saetzen auf Deutsch. Nenne die
behandelten Themen, Bibelstellen und wichtige Aussagen. Erfinde nichts, was nicht
im Text steht. Antworte ausschliesslich mit der Zusammenfassung.

Abschnitt:
---
{text}
---"""

# Note: this prompt deliberately gives NO example outline. An earlier version
# suggested "z. B. Begruessung, Lesung, Predigt, Fuerbitten, Abendmahl, Segen"
# and the model returned exactly those six words for an actual service, having
# derived nothing from the transcript at all. Same failure as priming Whisper
# with a word list: an example list is something to copy, not a hint.
FINAL_PROMPT = """Dir liegen Zusammenfassungen der Abschnitte eines deutschen
Gottesdienstes vor.

Erstelle daraus auf Deutsch:
1. Einen Absatz mit 5 bis 8 Saetzen ueber den gesamten Gottesdienst.
2. Danach eine Zeile "Gliederung:" gefolgt von 4 bis 8 Stichpunkten, jeweils mit
   "- " beginnend. Jeder Stichpunkt muss benennen, worum es an dieser Stelle
   konkret ging - das Thema, die Bibelstelle, das Lied oder die Aussage. Ein
   blosser liturgischer Name wie "Predigt" oder "Segen" ist nicht genug.
   Nimm nur Punkte auf, die im Text tatsaechlich vorkommen.

Beginne ohne Ueberschrift und ohne Vorrede. Erfinde nichts.

Abschnitts-Zusammenfassungen:
---
{text}
---"""


class SummaryUnavailable(RuntimeError):
    """Raised when the LLM cannot be reached - never fatal to the job."""


def run(doc: dict[str, Any], on_progress: Callable[[float], None] | None = None
        ) -> dict[str, Any]:
    transcript = _to_plain_text(doc)
    if len(transcript.strip()) < 400:
        raise SummaryUnavailable("Transkript ist zu kurz fuer eine Zusammenfassung")

    with httpx.Client(base_url=OLLAMA_URL, timeout=_REQUEST_TIMEOUT) as client:
        _ensure_model(client)

        chunks = _chunk(transcript)
        log.info("summarize: %d chunks via %s", len(chunks), LLM_MODEL)

        partials: list[str] = []
        for position, chunk in enumerate(chunks):
            partials.append(_complete(client, CHUNK_PROMPT.format(text=chunk)))
            if on_progress:
                on_progress((position + 1) / (len(chunks) + 1))

        if len(partials) == 1:
            combined = partials[0]
        else:
            combined = _complete(client, FINAL_PROMPT.format(text="\n\n".join(partials)))
        if on_progress:
            on_progress(1.0)

    summary, outline = _split_outline(combined)
    return {"summary": summary, "outline": outline, "model": LLM_MODEL}


def _to_plain_text(doc: dict[str, Any]) -> str:
    speakers = doc.get("speakers", {})
    lines: list[str] = []
    for segment in doc.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        if segment.get("type") == "music":
            lines.append(text)
            continue
        speaker = segment.get("speaker")
        label = (speakers.get(speaker, {}) or {}).get("label") or "Sprecher"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _chunk(text: str) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > LLM_CHUNK_CHARS and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _ensure_model(client: httpx.Client) -> None:
    try:
        response = client.get("/api/tags", timeout=httpx.Timeout(15.0))
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SummaryUnavailable(f"Ollama nicht erreichbar unter {OLLAMA_URL}") from exc

    installed = {m.get("name", "").split(":")[0]
                 for m in response.json().get("models", [])}
    if LLM_MODEL.split(":")[0] in installed:
        return

    log.info("pulling %s (first run only, this takes a while)", LLM_MODEL)
    try:
        with client.stream("POST", "/api/pull", json={"model": LLM_MODEL},
                           timeout=httpx.Timeout(3600.0, connect=15.0)) as stream:
            stream.raise_for_status()
            for _ in stream.iter_lines():
                pass
    except httpx.HTTPError as exc:
        raise SummaryUnavailable(f"Modell {LLM_MODEL} konnte nicht geladen werden") from exc


def _complete(client: httpx.Client, prompt: str) -> str:
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,  # ignored by models without a thinking mode
        "options": {"num_ctx": LLM_NUM_CTX, "temperature": 0.2},
    }
    try:
        response = client.post("/api/generate", json=payload)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SummaryUnavailable(f"Anfrage an Ollama fehlgeschlagen: {exc}") from exc
    return _THINK.sub("", response.json().get("response", "")).strip()


_HEADING = re.compile(r"^\s*(zusammenfassung|summary)\s*:?\s*$",
                      re.IGNORECASE | re.MULTILINE)


def _split_outline(text: str) -> tuple[str, list[str]]:
    marker = re.search(r"^\s*gliederung\s*:?\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not marker:
        return _strip_heading(text), []
    summary = _strip_heading(text[:marker.start()])
    outline = [
        re.sub(r"^[-*•]\s*", "", line).strip()
        for line in text[marker.end():].splitlines()
        if line.strip()
    ]
    return summary, [item for item in outline if item]


def _strip_heading(text: str) -> str:
    """Drop a leading "Zusammenfassung:" line the model adds despite being asked not to."""
    cleaned = _HEADING.sub("", text, count=1).strip()
    # Also handles the inline form, where the heading opens the first sentence.
    return re.sub(r"^(zusammenfassung|summary)\s*:\s*", "", cleaned,
                  count=1, flags=re.IGNORECASE).strip()
