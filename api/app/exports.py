"""Transcript exports: TXT, Markdown, SRT, VTT, DOCX."""
from __future__ import annotations

import io
import re
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from . import db
from .transcript import load

router = APIRouter(prefix="/api/jobs", tags=["export"])

FORMATS = {"txt", "md", "srt", "vtt", "docx"}
_FILENAME_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)


# A block is broken at these limits even when the speaker has not changed.
# Without them an imported transcript - which has no speakers at all, so every
# segment groups with the next - comes out as one unreadable paragraph running
# the length of the service.
MAX_BLOCK_SECONDS = 45.0
MAX_BLOCK_CHARS = 900


def speaker_label(doc: dict[str, Any], speaker_id: str | None) -> str | None:
    """The display name for a speaker, or None when the source has no speakers.

    Imported transcripts carry no diarization, and labelling every paragraph
    "Unbekannt" is worse than labelling none of them.
    """
    if not speaker_id:
        return None
    entry = doc.get("speakers", {}).get(speaker_id) or {}
    return entry.get("label") or speaker_id.replace("SPEAKER_", "Sprecher ")


def clock(seconds: float, *, millis_sep: str = ",") -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:  # rounding can tip a whole second
        ms, secs = 0, secs + 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{millis_sep}{ms:03d}"


def short_clock(seconds: float) -> str:
    total = int(max(0.0, float(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def grouped(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Merge consecutive segments from the same speaker into one block.

    Whisper emits a segment every few seconds; without this an export reads as a
    wall of one-line paragraphs.
    """
    block: dict[str, Any] | None = None
    for segment in doc.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        key = segment.get("marker") if segment.get("type") == "music" else segment.get("speaker")
        fits = (
            block is not None
            and block["key"] == key
            and segment.get("type") != "music"
            and len(block["text"]) + len(text) + 1 <= MAX_BLOCK_CHARS
            and segment.get("end", block["end"]) - block["start"] <= MAX_BLOCK_SECONDS
        )
        if fits:
            block["text"] += " " + text
            block["end"] = segment.get("end", block["end"])
        else:
            if block:
                yield block
            block = {
                "key": key,
                "type": segment.get("type", "speech"),
                "speaker": segment.get("speaker"),
                "start": segment.get("start", 0.0),
                "end": segment.get("end", 0.0),
                "text": text,
            }
    if block:
        yield block


def _title(job: Any, doc: dict[str, Any]) -> str:
    return job["title"] or doc.get("title") or "Transkript"


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------
def render_txt(job: Any, doc: dict[str, Any]) -> str:
    lines = [_title(job, doc)]
    if job["service_date"]:
        lines.append(job["service_date"])
    lines.append("")
    for block in grouped(doc):
        stamp = short_clock(block["start"])
        if block["type"] == "music":
            lines.append(f"[{stamp}] {block['text']}")
        else:
            label = speaker_label(doc, block["speaker"])
            prefix = f"{label}: " if label else ""
            lines.append(f"[{stamp}] {prefix}{block['text']}")
        lines.append("")
    return "\n".join(lines)


def render_md(job: Any, doc: dict[str, Any]) -> str:
    lines = [f"# {_title(job, doc)}", ""]
    if job["service_date"]:
        lines += [f"*{job['service_date']}*", ""]
    summary = doc.get("summary")
    if summary:
        lines += ["## Zusammenfassung", "", summary, "", "## Transkript", ""]
    for block in grouped(doc):
        stamp = short_clock(block["start"])
        if block["type"] == "music":
            lines += [f"`{stamp}` — *{block['text']}*", ""]
        else:
            label = speaker_label(doc, block["speaker"])
            heading = f"**{label}** `{stamp}`" if label else f"`{stamp}`"
            lines += [heading, "", block["text"], ""]
    return "\n".join(lines)


def _subtitles(doc: dict[str, Any], *, vtt: bool) -> str:
    sep = "." if vtt else ","
    out: list[str] = ["WEBVTT", ""] if vtt else []
    index = 1
    for segment in doc.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        speaker = ""
        if segment.get("type") != "music":
            label = speaker_label(doc, segment.get("speaker"))
            speaker = f"{label}: " if label else ""
        if not vtt:
            out.append(str(index))
        out.append(f"{clock(segment.get('start', 0), millis_sep=sep)} --> "
                   f"{clock(segment.get('end', 0), millis_sep=sep)}")
        out.append(f"{speaker}{text}")
        out.append("")
        index += 1
    return "\n".join(out)


def render_docx(job: Any, doc: dict[str, Any]) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    document = Document()
    document.add_heading(_title(job, doc), level=0)
    if job["service_date"]:
        document.add_paragraph(job["service_date"])

    summary = doc.get("summary")
    if summary:
        document.add_heading("Zusammenfassung", level=1)
        for para in str(summary).split("\n\n"):
            if para.strip():
                document.add_paragraph(para.strip())
        document.add_heading("Transkript", level=1)

    for block in grouped(doc):
        stamp = short_clock(block["start"])
        paragraph = document.add_paragraph()
        if block["type"] == "music":
            run = paragraph.add_run(f"{stamp}  {block['text']}")
            run.italic = True
            run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)
            continue
        label = speaker_label(doc, block["speaker"])
        if label:
            header = paragraph.add_run(f"{label}  ")
            header.bold = True
        time_run = paragraph.add_run(f"{stamp}\n")
        time_run.font.size = Pt(8)
        time_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        paragraph.add_run(block["text"])

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
@router.get("/{job_id}/export/{fmt}")
async def export(job_id: str, fmt: str):
    if fmt not in FORMATS:
        raise HTTPException(400, f"Unbekanntes Format: {fmt}")
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    doc = load(job_id)

    stem = _FILENAME_UNSAFE.sub("_", _title(job, doc)).strip("_ ") or "transkript"
    disposition = f'attachment; filename="{stem}.{fmt}"'

    if fmt == "docx":
        payload = render_docx(job, doc)
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": disposition},
        )

    if fmt == "txt":
        body, media = render_txt(job, doc), "text/plain; charset=utf-8"
    elif fmt == "md":
        body, media = render_md(job, doc), "text/markdown; charset=utf-8"
    elif fmt == "srt":
        body, media = _subtitles(doc, vtt=False), "application/x-subrip; charset=utf-8"
    else:
        body, media = _subtitles(doc, vtt=True), "text/vtt; charset=utf-8"

    return Response(body, media_type=media, headers={"Content-Disposition": disposition})
