"""The editable transcript document.

`transcript.json` is the single source of truth once the worker is finished.
Edits are merged in by id rather than replacing the document wholesale, so an
autosave racing with a stale tab cannot wipe out unrelated segments.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db, hymns
from .config import job_dir

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["transcript"])


def transcript_path(job_id: str) -> Path:
    return job_dir(job_id) / "transcript.json"


def load(job_id: str) -> dict[str, Any]:
    path = transcript_path(job_id)
    if not path.exists():
        raise HTTPException(404, "Transkript noch nicht verfuegbar")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save(job_id: str, doc: dict[str, Any]) -> None:
    """Atomic replace, so an interrupted write can never truncate the transcript."""
    path = transcript_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = db.now()
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class SegmentEdit(BaseModel):
    id: str
    text: str | None = None
    speaker: str | None = None


class SpeakerEdit(BaseModel):
    label: str = Field(max_length=120)


class TranscriptPatch(BaseModel):
    segments: list[SegmentEdit] = Field(default_factory=list)
    speakers: dict[str, SpeakerEdit] = Field(default_factory=dict)


def _with_hymns(job_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Attach hymn references to a response without persisting them.

    Derived rather than stored: it costs about a millisecond, it means all 122
    existing recordings gain the feature with no backfill or reprocessing, and
    editing a transcript cannot leave a stale list behind.
    """
    row = db.query_one("SELECT title FROM jobs WHERE id = ?", (job_id,))
    return {**doc, "hymns": hymns.collect(doc, row["title"] if row else None)}


@router.get("/{job_id}/transcript")
async def get_transcript(job_id: str) -> dict[str, Any]:
    return _with_hymns(job_id, load(job_id))


@router.patch("/{job_id}/transcript")
async def patch_transcript(job_id: str, payload: TranscriptPatch) -> dict[str, Any]:
    doc = load(job_id)

    if payload.segments:
        by_id = {s["id"]: s for s in doc.get("segments", [])}
        for edit in payload.segments:
            segment = by_id.get(edit.id)
            if segment is None:
                log.warning("job %s: edit for unknown segment %s", job_id, edit.id)
                continue
            if edit.text is not None and edit.text != segment.get("text"):
                segment["text"] = edit.text
                segment["edited"] = True
                # Word timings no longer describe the edited text; drop them
                # rather than let the player highlight the wrong words.
                segment.pop("words", None)
            if edit.speaker is not None:
                segment["speaker"] = edit.speaker

    if payload.speakers:
        speakers = doc.setdefault("speakers", {})
        for speaker_id, edit in payload.speakers.items():
            entry = speakers.setdefault(speaker_id, {})
            entry["label"] = edit.label

    save(job_id, doc)
    return _with_hymns(job_id, doc)


@router.get("/{job_id}/summary")
async def get_summary(job_id: str) -> dict[str, Any]:
    path = job_dir(job_id) / "summary.json"
    if not path.exists():
        raise HTTPException(404, "Zusammenfassung nicht verfuegbar")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
