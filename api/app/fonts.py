"""Fonts for the DOCX export.

A font is an ordinary .ttf or .otf uploaded once and then picked in the export
dialog. The file is kept as uploaded and written into every export that uses
it (see `docx_fonts.apply_font`), so the document looks the same on a machine
that has never had the font installed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db
from .config import FONTS_DIR
from .docx_fonts import FONT_EXTENSIONS, family_name

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fonts", tags=["fonts"])

MAX_FONT_BYTES = 10 * 1024 * 1024
MAX_NAME_LENGTH = 120


def font_path(font_id: str) -> Path:
    return FONTS_DIR / f"{font_id}.font"


def _font_or_404(font_id: str) -> Any:
    row = db.query_one("SELECT * FROM fonts WHERE id = ?", (font_id,))
    if row is None:
        raise HTTPException(404, "Schriftart nicht gefunden")
    return row


def _clean_name(name: str | None, fallback: str) -> str:
    cleaned = " ".join((name or "").split()).strip()
    return (cleaned or fallback)[:MAX_NAME_LENGTH]


class FontPatch(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)


@router.get("")
async def list_fonts() -> dict[str, Any]:
    rows = db.query("SELECT * FROM fonts ORDER BY name COLLATE NOCASE, created_at")
    return {"fonts": [dict(row) for row in rows]}


@router.post("", status_code=201)
async def upload_font(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> dict[str, Any]:
    filename = file.filename or "schrift.ttf"
    if Path(filename).suffix.lower() not in FONT_EXTENSIONS:
        raise HTTPException(400, "Nur TrueType- und OpenType-Schriften (.ttf, .otf)")

    payload = await file.read(MAX_FONT_BYTES + 1)
    if len(payload) > MAX_FONT_BYTES:
        raise HTTPException(413, "Die Schriftdatei ist zu groß (maximal 10 MB)")
    if not payload:
        raise HTTPException(400, "Die Datei ist leer")

    # The family name is what the document asks for, so a file we cannot read
    # one out of is no use - better to say so than to export a fallback font.
    family = family_name(payload)
    if not family:
        log.info("rejected font upload %r: no readable name table", filename)
        raise HTTPException(400, "Die Datei konnte nicht als Schriftart gelesen werden")

    font_id = db.new_id()
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    font_path(font_id).write_bytes(payload)

    stamp = db.now()
    db.execute(
        "INSERT INTO fonts (id, name, family, filename, size_bytes, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?)",
        (font_id, _clean_name(name, family), family, filename, len(payload), stamp, stamp),
    )
    return dict(_font_or_404(font_id))


@router.patch("/{font_id}")
async def rename_font(font_id: str, patch: FontPatch) -> dict[str, Any]:
    row = _font_or_404(font_id)
    db.update_row("fonts", font_id, name=_clean_name(patch.name, row["family"]))
    return dict(_font_or_404(font_id))


@router.delete("/{font_id}")
async def delete_font(font_id: str) -> dict[str, str]:
    _font_or_404(font_id)
    db.execute("DELETE FROM fonts WHERE id = ?", (font_id,))
    font_path(font_id).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.get("/{font_id}/file")
async def download_font(font_id: str) -> FileResponse:
    row = _font_or_404(font_id)
    path = font_path(font_id)
    if not path.exists():
        raise HTTPException(410, "Die Datei der Schriftart fehlt")
    return FileResponse(path, media_type="font/ttf", filename=row["filename"])
