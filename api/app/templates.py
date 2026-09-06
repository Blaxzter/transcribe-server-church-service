"""Word templates for the DOCX export.

A template is an ordinary .docx made in Word with placeholders such as
"{{Titel}}", "{{Lieder}}" or "{{Text}}" wherever the recording's data should go.
The file is kept as uploaded; the substitution happens at export time in
`exports.render_template`, so a template can be re-used for every service and
edited in Word whenever the layout should change.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db
from .config import TEMPLATES_DIR
from .exports import TEMPLATE_FIELDS, find_placeholders

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/templates", tags=["templates"])

MAX_TEMPLATE_BYTES = 20 * 1024 * 1024
MAX_NAME_LENGTH = 120


def template_path(template_id: str) -> Path:
    return TEMPLATES_DIR / f"{template_id}.docx"


def _serialize(row: Any) -> dict[str, Any]:
    entry = dict(row)
    try:
        entry["placeholders"] = json.loads(entry.get("placeholders") or "[]")
    except json.JSONDecodeError:
        entry["placeholders"] = []
    entry["unknown_placeholders"] = [
        name for name in entry["placeholders"] if name not in TEMPLATE_FIELDS
    ]
    return entry


def _template_or_404(template_id: str) -> Any:
    row = db.query_one("SELECT * FROM templates WHERE id = ?", (template_id,))
    if row is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    return row


def _clean_name(name: str | None, fallback: str) -> str:
    cleaned = " ".join((name or "").split()).strip()
    if not cleaned:
        cleaned = Path(fallback).stem.replace("_", " ").strip() or "Vorlage"
    return cleaned[:MAX_NAME_LENGTH]


class TemplatePatch(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)


@router.get("")
async def list_templates() -> dict[str, Any]:
    rows = db.query("SELECT * FROM templates ORDER BY name COLLATE NOCASE, created_at")
    return {
        "templates": [_serialize(row) for row in rows],
        "fields": list(TEMPLATE_FIELDS.keys()),
    }


@router.post("", status_code=201)
async def upload_template(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> dict[str, Any]:
    filename = file.filename or "vorlage.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(400, "Nur Word-Dokumente (.docx) können als Vorlage dienen")

    payload = await file.read(MAX_TEMPLATE_BYTES + 1)
    if len(payload) > MAX_TEMPLATE_BYTES:
        raise HTTPException(413, "Die Vorlage ist zu groß (maximal 20 MB)")
    if not payload:
        raise HTTPException(400, "Die Datei ist leer")

    template_id = db.new_id()
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = template_path(template_id)
    path.write_bytes(payload)
    try:
        placeholders = find_placeholders(path)
    except Exception:
        path.unlink(missing_ok=True)
        log.info("rejected template upload %r: not a readable .docx", filename, exc_info=True)
        raise HTTPException(400, "Die Datei konnte nicht als Word-Dokument gelesen werden")

    stamp = db.now()
    db.execute(
        "INSERT INTO templates (id, name, filename, placeholders, size_bytes,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (template_id, _clean_name(name, filename), filename, json.dumps(placeholders),
         len(payload), stamp, stamp),
    )
    return _serialize(_template_or_404(template_id))


@router.patch("/{template_id}")
async def rename_template(template_id: str, patch: TemplatePatch) -> dict[str, Any]:
    _template_or_404(template_id)
    db.update_row("templates", template_id, name=_clean_name(patch.name, "Vorlage"))
    return _serialize(_template_or_404(template_id))


@router.delete("/{template_id}")
async def delete_template(template_id: str) -> dict[str, str]:
    _template_or_404(template_id)
    db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    template_path(template_id).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.get("/{template_id}/file")
async def download_template(template_id: str) -> FileResponse:
    row = _template_or_404(template_id)
    path = template_path(template_id)
    if not path.exists():
        raise HTTPException(410, "Die Datei der Vorlage fehlt")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=row["filename"],
    )
