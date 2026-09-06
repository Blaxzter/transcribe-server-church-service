"""Transcript exports: TXT, Markdown, SRT, VTT, DOCX - plain or from a Word template.

The person who actually uses these exports refines the transcript in Word, and
the old fixed layout meant hand-deleting every speaker label and timestamp
first. So an export is now described by `ExportOptions`: which speakers and
which sections of the service to keep, and how the text is laid out. Every
renderer works from the same `layout()` - a flat list of blocks - so the
formats cannot drift apart, and a Word template fills its `{{Text}}`
placeholder with exactly the same blocks.
"""
from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import db, docx_fonts, hymns
from .transcript import load

router = APIRouter(prefix="/api/jobs", tags=["export"])

FORMATS = {"txt", "md", "srt", "vtt", "docx"}
_FILENAME_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


# A block is broken at these limits even when the speaker has not changed.
# Without them an imported transcript - which has no speakers at all, so every
# segment groups with the next - comes out as one unreadable paragraph running
# the length of the service.
MAX_BLOCK_SECONDS = 45.0
MAX_BLOCK_CHARS = 900

# A pause this long with no music detected still ends a section. It only
# matters for legacy imports, which carry no music markers at all and would
# otherwise be a single section.
SECTION_GAP_SECONDS = 120.0

# How much of a section's opening the UI shows to tell sections apart.
SECTION_PREVIEW_CHARS = 110


Paragraphs = Literal["blocks", "segment", "speaker", "section"]
SectionBreak = Literal["none", "blank", "heading", "page"]


class ExportOptions(BaseModel):
    """What goes into an export and how it is laid out.

    The defaults reproduce the original fixed export, so a plain GET keeps
    working exactly as before. The UI stores the user's own defaults locally.
    """

    # Which speakers to keep. None keeps every speaker; an empty list keeps none
    # of the labelled speech (music markers are unaffected).
    speakers: list[str] | None = None
    # Which sections (see `sections()`) to keep, by index. None keeps all.
    sections: list[int] | None = None

    speaker_labels: bool = True
    timestamps: bool = True
    music: bool = True
    header: bool = True
    summary: bool = True

    # How the text of a section is split into paragraphs:
    #   blocks  - at every speaker change, and at most 45 s / 900 chars each
    #   segment - one paragraph per recognised segment (a sentence or two)
    #   speaker - only at speaker changes, however long that runs
    #   section - the whole section as one paragraph
    paragraphs: Paragraphs = "blocks"
    # What separates two sections in the output.
    section_break: SectionBreak = "none"

    # Id of a stored Word template; only meaningful for DOCX.
    template: str | None = Field(default=None, max_length=64)
    # Id of an uploaded font. Only for the built-in DOCX layout - a template
    # brings its own fonts and they are left alone.
    font: str | None = Field(default=None, max_length=64)


# --------------------------------------------------------------------------
# Helpers shared by every renderer
# --------------------------------------------------------------------------
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


def _field(job: Any, key: str) -> Any:
    """Read a job column from a sqlite Row or a plain dict alike."""
    return job[key] if key in job.keys() else None


def _title(job: Any, doc: dict[str, Any]) -> str:
    return _field(job, "title") or doc.get("title") or "Transkript"


def _german_date(iso: str | None) -> str:
    """'2023-08-18' -> '18.08.2023'; anything unparseable is passed through."""
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
def sections(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The service cut into its natural parts.

    A section is a run of speech between two pieces of music - greeting, sermon,
    announcements - which is the unit someone wants to pick when they only need
    the sermon. Music markers count as the lead-in of the section that follows
    them (or the tail of the last one), so the organ before the greeting is
    exported with the greeting.
    """
    result: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_music: list[dict[str, Any]] = []
    previous_end: float | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            result.append(current)
        current = None

    for segment in doc.get("segments", []):
        if segment.get("type") == "music":
            close()
            pending_music.append(segment)
            previous_end = None
            continue
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        long_pause = previous_end is not None and start - previous_end > SECTION_GAP_SECONDS
        if current is None or long_pause:
            close()
            current = {
                "index": len(result),
                "start": start,
                "end": end,
                "music": pending_music,
                "segments": [],
                "speakers": {},
                "preview": "",
            }
            pending_music = []
        current["segments"].append(segment)
        current["end"] = max(current["end"], end)
        speaker = segment.get("speaker")
        if speaker:
            current["speakers"][speaker] = current["speakers"].get(speaker, 0.0) + max(0.0, end - start)
        if len(current["preview"]) < SECTION_PREVIEW_CHARS:
            current["preview"] = (current["preview"] + " " + text).strip()
        previous_end = end
    close()

    if pending_music:
        if result:
            result[-1]["music"] = result[-1]["music"] + pending_music
        else:
            # Nothing but music - one section so the markers can still be exported.
            result.append({
                "index": 0,
                "start": float(pending_music[0].get("start") or 0.0),
                "end": float(pending_music[-1].get("end") or 0.0),
                "music": pending_music,
                "segments": [],
                "speakers": {},
                "preview": "",
            })

    for section in result:
        section["preview"] = _shorten(section["preview"], SECTION_PREVIEW_CHARS)
    return result


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def section_summaries(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The sections as the API reports them - without the segments themselves."""
    out = []
    for section in sections(doc):
        out.append({
            "index": section["index"],
            "start": round(section["start"], 2),
            "end": round(section["end"], 2),
            "speakers": {k: round(v, 1) for k, v in section["speakers"].items()},
            "segment_count": len(section["segments"]),
            "words": sum(len((s.get("text") or "").split()) for s in section["segments"]),
            "music": [
                {"text": (m.get("text") or "").strip(), "start": round(float(m.get("start") or 0), 2)}
                for m in section["music"]
            ],
            "preview": section["preview"],
        })
    return out


# --------------------------------------------------------------------------
# Layout: options + transcript -> blocks
# --------------------------------------------------------------------------
@dataclass
class Block:
    kind: Literal["paragraph", "music", "heading", "break"]
    text: str = ""
    # Display label of the speaker (already resolved), None when unlabelled.
    speaker: str | None = None
    start: float = 0.0
    end: float = 0.0
    # For "break": which kind of separator. For "heading": the section number.
    mode: str = ""
    section: int = 0
    # Speaker ids that contributed; used to decide whether a merged paragraph
    # still belongs to one person.
    speaker_ids: set[str] = field(default_factory=set)


def _keeps(segment: dict[str, Any], options: ExportOptions) -> bool:
    if options.speakers is None:
        return True
    # Segments without a speaker (imports, or gaps the diarizer skipped) belong
    # to nobody, so a speaker filter that names someone drops them. An empty
    # filter keeps nothing, which is what "no speaker selected" should mean.
    speaker = segment.get("speaker")
    return bool(speaker) and speaker in options.speakers


def _paragraphs(section: dict[str, Any], doc: dict[str, Any],
                options: ExportOptions) -> Iterator[Block]:
    """Fold the kept segments of one section into paragraphs."""
    mode = options.paragraphs
    block: Block | None = None
    for segment in section["segments"]:
        if not _keeps(segment, options):
            continue
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker")
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)

        if block is None:
            fits = False
        elif mode == "segment":
            fits = False
        elif mode == "section":
            fits = True
        elif mode == "speaker":
            fits = (speaker in block.speaker_ids) if speaker else not block.speaker_ids
        else:  # blocks
            same = (speaker in block.speaker_ids) if speaker else not block.speaker_ids
            fits = (
                same
                and len(block.text) + len(text) + 1 <= MAX_BLOCK_CHARS
                and end - block.start <= MAX_BLOCK_SECONDS
            )

        if fits and block is not None:
            block.text += " " + text
            block.end = max(block.end, end)
            if speaker:
                block.speaker_ids.add(speaker)
        else:
            if block is not None:
                yield _finish(block, doc)
            block = Block(
                kind="paragraph", text=text, start=start, end=end,
                section=section["index"],
                speaker_ids={speaker} if speaker else set(),
            )
    if block is not None:
        yield _finish(block, doc)


def _finish(block: Block, doc: dict[str, Any]) -> Block:
    # A paragraph that merged several people has no honest label.
    if len(block.speaker_ids) == 1:
        block.speaker = speaker_label(doc, next(iter(block.speaker_ids)))
    return block


def layout(doc: dict[str, Any], options: ExportOptions) -> list[Block]:
    """The transcript body as an ordered list of blocks."""
    blocks: list[Block] = []
    wanted = None if options.sections is None else set(options.sections)
    first = True
    for section in sections(doc):
        if wanted is not None and section["index"] not in wanted:
            continue
        body = list(_paragraphs(section, doc, options))
        music: list[Block] = []
        for m in section["music"] if options.music else []:
            text = (m.get("text") or "").strip()
            if not text:
                continue
            # A hymn sung in four verses is detected as four pieces of music;
            # four identical lines in a row say nothing more than one.
            if music and music[-1].text == text:
                music[-1].end = float(m.get("end") or music[-1].end)
                continue
            music.append(Block(kind="music", text=text, start=float(m.get("start") or 0.0),
                               end=float(m.get("end") or 0.0), section=section["index"]))
        if not body and not music:
            continue
        if not first and options.section_break != "none":
            blocks.append(Block(kind="break", mode=options.section_break,
                                section=section["index"]))
        if options.section_break == "heading":
            blocks.append(Block(kind="heading", text=f"Abschnitt {section['index'] + 1}",
                                start=section["start"], end=section["end"],
                                section=section["index"]))
        blocks.extend(music)
        blocks.extend(body)
        first = False
    return blocks


def grouped(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Merge consecutive segments from the same speaker into one block.

    Kept for callers and tests that predate `layout()`; it is the default
    layout rendered as plain dicts.
    """
    for block in layout(doc, ExportOptions()):
        if block.kind not in ("paragraph", "music"):
            continue
        yield {
            "key": block.text if block.kind == "music" else block.speaker,
            "type": "speech" if block.kind == "paragraph" else "music",
            "speaker": next(iter(block.speaker_ids)) if len(block.speaker_ids) == 1 else None,
            "start": block.start,
            "end": block.end,
            "text": block.text,
        }


def _speaker_names(doc: dict[str, Any], options: ExportOptions) -> list[str]:
    ids = list(doc.get("speakers", {}).keys())
    if options.speakers is not None:
        ids = [s for s in ids if s in options.speakers]
    names = [speaker_label(doc, s) for s in ids]
    return [n for n in names if n]


def _summary_paragraphs(doc: dict[str, Any]) -> list[str]:
    summary = doc.get("summary")
    if not summary:
        return []
    return [p.strip() for p in str(summary).split("\n\n") if p.strip()]


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------
def _line_prefix(block: Block, options: ExportOptions) -> str:
    parts = []
    if options.timestamps:
        parts.append(f"[{short_clock(block.start)}]")
    if options.speaker_labels and block.speaker:
        parts.append(f"{block.speaker}:")
    return " ".join(parts) + (" " if parts else "")


def render_txt(job: Any, doc: dict[str, Any],
               options: ExportOptions | None = None) -> str:
    options = options or ExportOptions()
    lines: list[str] = []
    if options.header:
        lines.append(_title(job, doc))
        if _field(job, "service_date"):
            lines.append(job["service_date"])
        lines.append("")
    if options.summary and _summary_paragraphs(doc):
        lines.append("Zusammenfassung")
        lines.append("")
        for para in _summary_paragraphs(doc):
            lines += [para, ""]
        lines += ["Transkript", ""]
    for block in layout(doc, options):
        if block.kind == "break":
            if block.mode == "page":
                lines += ["-" * 40, ""]
            elif block.mode == "blank":
                lines.append("")
            continue
        if block.kind == "heading":
            stamp = f" ({short_clock(block.start)})" if options.timestamps else ""
            lines += [f"{block.text}{stamp}", ""]
            continue
        if block.kind == "music":
            stamp = f"[{short_clock(block.start)}] " if options.timestamps else ""
            lines += [f"{stamp}{block.text}", ""]
            continue
        lines += [f"{_line_prefix(block, options)}{block.text}", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_md(job: Any, doc: dict[str, Any],
              options: ExportOptions | None = None) -> str:
    options = options or ExportOptions()
    lines: list[str] = []
    if options.header:
        lines += [f"# {_title(job, doc)}", ""]
        if _field(job, "service_date"):
            lines += [f"*{job['service_date']}*", ""]
    if options.summary and _summary_paragraphs(doc):
        lines += ["## Zusammenfassung", ""]
        for para in _summary_paragraphs(doc):
            lines += [para, ""]
        lines += ["## Transkript", ""]
    for block in layout(doc, options):
        if block.kind == "break":
            if block.mode == "page":
                lines += ["---", ""]
            elif block.mode == "blank":
                lines.append("")
            continue
        if block.kind == "heading":
            stamp = f" `{short_clock(block.start)}`" if options.timestamps else ""
            lines += [f"## {block.text}{stamp}", ""]
            continue
        if block.kind == "music":
            stamp = f"`{short_clock(block.start)}` — " if options.timestamps else ""
            lines += [f"{stamp}*{block.text}*", ""]
            continue
        heading_parts = []
        if options.speaker_labels and block.speaker:
            heading_parts.append(f"**{block.speaker}**")
        if options.timestamps:
            heading_parts.append(f"`{short_clock(block.start)}`")
        if heading_parts:
            lines += [" ".join(heading_parts), ""]
        lines += [block.text, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _subtitles(doc: dict[str, Any], *, vtt: bool,
               options: ExportOptions | None = None) -> str:
    options = options or ExportOptions()
    sep = "." if vtt else ","
    out: list[str] = ["WEBVTT", ""] if vtt else []
    index = 1
    wanted = None if options.sections is None else set(options.sections)
    for section in sections(doc):
        if wanted is not None and section["index"] not in wanted:
            continue
        entries: list[dict[str, Any]] = []
        if options.music:
            entries += section["music"]
        entries += [s for s in section["segments"] if _keeps(s, options)]
        entries.sort(key=lambda s: float(s.get("start") or 0.0))
        for segment in entries:
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            speaker = ""
            if segment.get("type") != "music" and options.speaker_labels:
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


# --- DOCX -------------------------------------------------------------------
def _write_paragraph(paragraph: Any, block: Block, options: ExportOptions) -> None:
    """Fill a python-docx paragraph with one block, the same way in every DOCX."""
    from docx.shared import Pt, RGBColor

    if block.kind == "music":
        stamp = f"{short_clock(block.start)}  " if options.timestamps else ""
        run = paragraph.add_run(f"{stamp}{block.text}")
        run.italic = True
        run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)
        return
    if block.kind == "heading":
        stamp = f"  {short_clock(block.start)}" if options.timestamps else ""
        run = paragraph.add_run(f"{block.text}{stamp}")
        run.bold = True
        return
    if options.speaker_labels and block.speaker:
        header = paragraph.add_run(f"{block.speaker}  ")
        header.bold = True
    if options.timestamps:
        time_run = paragraph.add_run(f"{short_clock(block.start)}\n")
        time_run.font.size = Pt(8)
        time_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    paragraph.add_run(block.text)


def _add_page_break(paragraph: Any) -> None:
    from docx.enum.text import WD_BREAK

    paragraph.add_run().add_break(WD_BREAK.PAGE)


def _page_setup(document: Any) -> None:
    """A4 with the margins a German Word document starts out with.

    python-docx builds on a US Letter template, which is a page nobody here
    prints on - and it made the export preview show margins that no printed
    copy would ever have.
    """
    from docx.shared import Cm

    for section in document.sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)


def render_docx(job: Any, doc: dict[str, Any],
                options: ExportOptions | None = None,
                font: tuple[str, bytes] | None = None) -> bytes:
    """The built-in DOCX layout. `font` is a (family name, file) to embed."""
    from docx import Document

    options = options or ExportOptions()
    document = Document()
    _page_setup(document)
    if options.header:
        document.add_heading(_title(job, doc), level=0)
        if _field(job, "service_date"):
            document.add_paragraph(job["service_date"])

    if options.summary and _summary_paragraphs(doc):
        document.add_heading("Zusammenfassung", level=1)
        for para in _summary_paragraphs(doc):
            document.add_paragraph(para)
        document.add_heading("Transkript", level=1)

    for block in layout(doc, options):
        if block.kind == "break":
            if block.mode == "page":
                _add_page_break(document.add_paragraph())
            elif block.mode == "blank":
                document.add_paragraph()
            continue
        if block.kind == "heading":
            stamp = f"  {short_clock(block.start)}" if options.timestamps else ""
            document.add_heading(f"{block.text}{stamp}", level=2)
            continue
        _write_paragraph(document.add_paragraph(), block, options)

    buffer = io.BytesIO()
    document.save(buffer)
    payload = buffer.getvalue()
    return docx_fonts.apply_font(payload, *font) if font else payload


# --- DOCX from a template ---------------------------------------------------
# The placeholders a template may use. Matching is case-insensitive and ignores
# whitespace inside the braces, so "{{ titel }}" works as well as "{{Titel}}".
# Whether one expands to a piece of text inside its paragraph or to a run of
# whole paragraphs decides how it is substituted.
TEMPLATE_FIELDS: dict[str, str] = {
    "titel": "inline",
    "datum": "inline",
    "dauer": "inline",
    "sprecher": "inline",
    "lieder": "inline",
    "liederliste": "paragraphs",
    "zusammenfassung": "paragraphs",
    "text": "blocks",
}

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-zÄÖÜäöüß_]+)\s*\}\}")


def _iter_paragraphs(container: Any) -> Iterator[Any]:
    """Every paragraph in a document part, including those inside tables."""
    for paragraph in container.paragraphs:
        yield paragraph
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_paragraphs(cell)


def _all_paragraphs(document: Any) -> list[Any]:
    found = list(_iter_paragraphs(document))
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header,
                     section.first_page_footer):
            if part is not None and not part.is_linked_to_previous:
                found.extend(_iter_paragraphs(part))
    return found


def find_placeholders(path: Path | str) -> list[str]:
    """Placeholder names used in a template, lower-cased, in order of first use."""
    from docx import Document

    document = Document(str(path))
    seen: list[str] = []
    for paragraph in _all_paragraphs(document):
        for match in PLACEHOLDER.finditer(paragraph.text):
            name = match.group(1).lower()
            if name not in seen:
                seen.append(name)
    return seen


def _insert_paragraph_after(paragraph: Any) -> Any:
    """A new, empty paragraph right after this one, with the same paragraph style."""
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    new_p = OxmlElement("w:p")
    if paragraph._p.pPr is not None:
        new_p.append(copy.deepcopy(paragraph._p.pPr))
    paragraph._p.addnext(new_p)
    return Paragraph(new_p, paragraph._parent)


def _substitute(paragraph: Any, spans: list[tuple[int, int, str]]) -> None:
    """Replace character spans of a paragraph without flattening its runs.

    Word tends to split "{{Titel}}" over several runs the moment someone edits
    it. Each span is located in the joined text and its replacement is written
    into the first run it touches; the other runs lose their share of the span
    and keep their formatting.
    """
    runs = paragraph.runs
    if not spans or not runs:
        return
    starts: list[int] = []
    offset = 0
    for run in runs:
        starts.append(offset)
        offset += len(run.text)
    new_texts = [run.text for run in runs]
    # Work backwards so earlier offsets stay valid while runs are rewritten.
    for a, b, replacement in sorted(spans, reverse=True):
        for i, run_start in enumerate(starts):
            run_end = run_start + len(runs[i].text)
            if run_end <= a or run_start >= b:
                continue
            lo, hi = max(a, run_start) - run_start, min(b, run_end) - run_start
            current = new_texts[i]
            piece = replacement if run_start <= a else ""
            new_texts[i] = current[:lo] + piece + current[hi:]
    for run, value in zip(runs, new_texts):
        if run.text != value:
            run.text = value


def _replace_inline(paragraph: Any, resolve: Any) -> None:
    text = paragraph.text
    spans = [(m.start(), m.end(), resolve(m.group(1).lower()))
             for m in PLACEHOLDER.finditer(text)
             if TEMPLATE_FIELDS.get(m.group(1).lower()) == "inline"]
    _substitute(paragraph, spans)


def _clear_runs(paragraph: Any) -> None:
    for run in list(paragraph.runs):
        run._r.getparent().remove(run._r)


def _expand_block_placeholder(paragraph: Any, match: re.Match[str], blocks: list[Block],
                              options: ExportOptions) -> None:
    """Replace a block placeholder with a run of paragraphs.

    The placeholder paragraph carries the style the author chose (a bullet for
    "{{Liederliste}}", body text for "{{Text}}"); every generated paragraph
    copies it, so the template decides what the transcript looks like. Text
    the author wrote before or after the placeholder in the same paragraph
    stays, as its own paragraph on either side of the generated ones.
    """
    text = paragraph.text
    before, after = text[:match.start()], text[match.end():]
    anchor = paragraph
    if before.strip():
        # Keep the lead text in place and let the blocks follow it.
        _substitute(paragraph, [(match.start(), len(text), "")])
        for block in blocks:
            anchor = _insert_paragraph_after(anchor)
            _write_block_into(anchor, block, options)
    else:
        _clear_runs(anchor)
        if blocks:
            _write_block_into(anchor, blocks[0], options)
        for block in blocks[1:]:
            anchor = _insert_paragraph_after(anchor)
            _write_block_into(anchor, block, options)
    if after.strip():
        anchor = _insert_paragraph_after(anchor)
        anchor.add_run(after.lstrip())


def _write_block_into(paragraph: Any, block: Block, options: ExportOptions) -> None:
    if block.kind == "break":
        if block.mode == "page":
            _add_page_break(paragraph)
        # "blank" is an empty paragraph, which this already is.
        return
    _write_paragraph(paragraph, block, options)


def render_template(template_path: Path | str, job: Any, doc: dict[str, Any],
                    options: ExportOptions) -> bytes:
    from docx import Document

    document = Document(str(template_path))
    hymn_numbers = [str(h["number"]) for h in hymns.extract(doc)]
    inline_values = {
        "titel": _title(job, doc),
        "datum": _german_date(_field(job, "service_date")),
        "dauer": short_clock(float(doc.get("duration") or _field(job, "duration_s") or 0.0)),
        "sprecher": ", ".join(_speaker_names(doc, options)),
        "lieder": ", ".join(hymn_numbers),
    }
    body = layout(doc, options)
    block_values: dict[str, list[Block]] = {
        "liederliste": [Block(kind="paragraph", text=n) for n in hymn_numbers],
        "zusammenfassung": [Block(kind="paragraph", text=p) for p in _summary_paragraphs(doc)],
        "text": body,
    }
    # Plain paragraphs for the summary and hymn list: no labels, no stamps.
    plain = ExportOptions(speaker_labels=False, timestamps=False)

    for paragraph in _all_paragraphs(document):
        if "{{" not in paragraph.text:
            continue
        _replace_inline(paragraph, lambda name: inline_values.get(name, ""))
        block_matches = [m for m in PLACEHOLDER.finditer(paragraph.text)
                         if TEMPLATE_FIELDS.get(m.group(1).lower()) in ("paragraphs", "blocks")]
        if not block_matches:
            continue
        # One block placeholder per paragraph; a second one would have nowhere
        # sensible to go and is dropped with the paragraph's text.
        match = block_matches[0]
        name = match.group(1).lower()
        _expand_block_placeholder(paragraph, match, block_values.get(name, []),
                                  options if name == "text" else plain)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def _job_or_404(job_id: str) -> Any:
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    return job


def _template_path(template_id: str) -> Path:
    from . import templates

    row = db.query_one("SELECT * FROM templates WHERE id = ?", (template_id,))
    if row is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    path = templates.template_path(row["id"])
    if not path.exists():
        raise HTTPException(410, "Die Datei der Vorlage fehlt")
    return path


def _font(font_id: str) -> tuple[str, bytes]:
    """(family name, file) for a stored font."""
    from . import fonts

    row = db.query_one("SELECT * FROM fonts WHERE id = ?", (font_id,))
    if row is None:
        raise HTTPException(404, "Schriftart nicht gefunden")
    path = fonts.font_path(row["id"])
    if not path.exists():
        raise HTTPException(410, "Die Datei der Schriftart fehlt")
    return row["family"], path.read_bytes()


def build_export(job: Any, doc: dict[str, Any], fmt: str,
                 options: ExportOptions) -> tuple[bytes | str, str]:
    """(payload, media type) for a format, honouring the options."""
    if fmt == "docx":
        if options.template:
            payload = render_template(_template_path(options.template), job, doc, options)
        else:
            payload = render_docx(job, doc, options,
                                  _font(options.font) if options.font else None)
        return payload, DOCX_MEDIA_TYPE
    if fmt == "txt":
        return render_txt(job, doc, options), "text/plain; charset=utf-8"
    if fmt == "md":
        return render_md(job, doc, options), "text/markdown; charset=utf-8"
    if fmt == "srt":
        return _subtitles(doc, vtt=False, options=options), "application/x-subrip; charset=utf-8"
    return _subtitles(doc, vtt=True, options=options), "text/vtt; charset=utf-8"


def _respond(job: Any, doc: dict[str, Any], fmt: str, options: ExportOptions) -> Response:
    if fmt not in FORMATS:
        raise HTTPException(400, f"Unbekanntes Format: {fmt}")
    payload, media = build_export(job, doc, fmt, options)
    stem = _FILENAME_UNSAFE.sub("_", _title(job, doc)).strip("_ ") or "transkript"
    headers = {"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'}
    if isinstance(payload, bytes):
        return StreamingResponse(io.BytesIO(payload), media_type=media, headers=headers)
    return Response(payload, media_type=media, headers=headers)


@router.get("/{job_id}/sections")
async def get_sections(job_id: str) -> dict[str, Any]:
    _job_or_404(job_id)
    return {"sections": section_summaries(load(job_id))}


@router.get("/{job_id}/export/{fmt}")
async def export(job_id: str, fmt: str):
    """The fixed, everything-included export; what the old buttons produced."""
    job = _job_or_404(job_id)
    return _respond(job, load(job_id), fmt, ExportOptions())


@router.post("/{job_id}/export/{fmt}")
async def export_with_options(job_id: str, fmt: str, options: ExportOptions):
    job = _job_or_404(job_id)
    return _respond(job, load(job_id), fmt, options)
