"""Resumable uploads: the tus 1.0.0 core protocol plus the creation extension.

Why this exists: Cloudflare Tunnel caps a single proxied request body at 100 MB,
and a 90-minute service recording is comfortably larger. The client
(tus-js-client) slices the file into 8 MB PATCHes, so no individual request ever
approaches the cap, and a dropped connection resumes instead of restarting.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from . import db
from .config import AUDIO_EXTENSIONS, MAX_UPLOAD_BYTES, UPLOADS_DIR, job_dir
from .jobs import create_job_from_upload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["upload"])

TUS_VERSION = "1.0.0"
CHUNK_READ_SIZE = 1024 * 1024

_BASE_HEADERS = {
    "Tus-Resumable": TUS_VERSION,
    "Cache-Control": "no-store",
}

_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)


def sanitize_filename(name: str) -> str:
    """Strip path components and anything that could escape the data directory."""
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = _UNSAFE.sub("_", name)
    name = name.lstrip(".") or "aufnahme"
    return name[:180]


def parse_upload_metadata(raw: str | None) -> dict[str, str]:
    """`Upload-Metadata: key <base64>,key2 <base64>` -> plain dict."""
    result: dict[str, str] = {}
    if not raw:
        return result
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, encoded = pair.partition(" ")
        if not encoded:
            result[key] = ""
            continue
        try:
            result[key] = base64.b64decode(encoded).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            log.warning("undecodable Upload-Metadata value for key %r", key)
    return result


def _part_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.part"


@router.options("")
@router.options("/{upload_id}")
async def tus_options(upload_id: str | None = None) -> Response:
    return Response(
        status_code=204,
        headers={
            **_BASE_HEADERS,
            "Tus-Version": TUS_VERSION,
            "Tus-Extension": "creation,termination",
            "Tus-Max-Size": str(MAX_UPLOAD_BYTES),
        },
    )


@router.post("")
async def tus_create(request: Request) -> Response:
    try:
        length = int(request.headers.get("Upload-Length", ""))
    except ValueError:
        raise HTTPException(400, "Upload-Length header is required")
    if length <= 0:
        raise HTTPException(400, "Upload-Length must be positive")
    if length > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Datei zu gross (max {MAX_UPLOAD_BYTES} Bytes)")

    metadata = parse_upload_metadata(request.headers.get("Upload-Metadata"))
    filename = sanitize_filename(metadata.get("filename") or "aufnahme")
    if Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(415, f"Nicht unterstuetztes Format: {Path(filename).suffix or 'unbekannt'}")

    upload_id = db.new_id()
    path = _part_path(upload_id)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path.touch()

    db.execute(
        "INSERT INTO uploads (id, path, filename, length_bytes, offset_bytes, metadata,"
        " created_at, updated_at) VALUES (?,?,?,?,0,?,?,?)",
        (upload_id, str(path), filename, length,
         request.headers.get("Upload-Metadata", ""), db.now(), db.now()),
    )
    return Response(
        status_code=201,
        headers={**_BASE_HEADERS, "Location": f"/files/{upload_id}", "Upload-Offset": "0"},
    )


@router.head("/{upload_id}")
async def tus_head(upload_id: str) -> Response:
    row = db.query_one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if row is None:
        raise HTTPException(404, "Upload nicht gefunden")
    return Response(
        status_code=200,
        headers={
            **_BASE_HEADERS,
            "Upload-Offset": str(row["offset_bytes"]),
            "Upload-Length": str(row["length_bytes"]),
        },
    )


@router.patch("/{upload_id}")
async def tus_patch(upload_id: str, request: Request) -> Response:
    if request.headers.get("Content-Type") != "application/offset+octet-stream":
        raise HTTPException(415, "Content-Type must be application/offset+octet-stream")

    row = db.query_one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if row is None:
        raise HTTPException(404, "Upload nicht gefunden")

    if row["job_id"]:
        # Already finalized: the part file has been moved into its job
        # directory. This is a client retrying a PATCH whose response was lost,
        # so acknowledge it rather than failing on the missing file.
        return Response(status_code=204, headers={
            **_BASE_HEADERS,
            "Upload-Offset": str(row["length_bytes"]),
            "Transcribe-Job-Id": row["job_id"],
        })

    try:
        client_offset = int(request.headers.get("Upload-Offset", ""))
    except ValueError:
        raise HTTPException(400, "Upload-Offset header is required")

    offset = row["offset_bytes"]
    if client_offset != offset:
        # 409 is what tus clients use to trigger a HEAD-and-resume.
        raise HTTPException(409, f"Offset mismatch: server at {offset}")

    path = Path(row["path"])
    length = row["length_bytes"]

    # Append streaming, so a 500 MB upload never lands in memory.
    written = offset
    with path.open("r+b") as fh:
        fh.seek(offset)
        async for chunk in request.stream():
            if not chunk:
                continue
            if written + len(chunk) > length:
                chunk = chunk[: length - written]
                if not chunk:
                    break
            fh.write(chunk)
            written += len(chunk)
        fh.flush()

    db.execute(
        "UPDATE uploads SET offset_bytes = ?, updated_at = ? WHERE id = ?",
        (written, db.now(), upload_id),
    )

    headers = {**_BASE_HEADERS, "Upload-Offset": str(written)}
    if written >= length:
        job_id = await _finalize(upload_id, path, row["filename"])
        headers["Transcribe-Job-Id"] = job_id
    return Response(status_code=204, headers=headers)


@router.delete("/{upload_id}")
async def tus_delete(upload_id: str) -> Response:
    row = db.query_one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if row is not None:
        Path(row["path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    return Response(status_code=204, headers=_BASE_HEADERS)


async def _finalize(upload_id: str, part_path: Path, filename: str) -> str:
    """Move the completed part file into its job directory and queue the job."""
    job_id = db.new_id()
    target_dir = job_dir(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original{Path(filename).suffix.lower()}"
    part_path.replace(target)

    db.execute("UPDATE uploads SET job_id = ?, updated_at = ? WHERE id = ?",
               (job_id, db.now(), upload_id))
    await create_job_from_upload(job_id, filename, target)
    log.info("upload %s finalized as job %s (%s)", upload_id, job_id, filename)
    return job_id
