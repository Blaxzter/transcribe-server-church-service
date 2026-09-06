"""Job lifecycle: creation, listing, progress streaming, media delivery."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db
from .config import REDIS_URL, job_dir
from .events import HEARTBEAT_KEY, bus

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

WORKER_FUNCTION = "transcribe_job"
_pool: ArqRedis | None = None

# Ordered so the UI can render a progress rail without duplicating this list.
STAGES = [
    "normalize", "peaks", "music", "vad",
    "asr", "align", "diarize", "merge", "summarize",
]


async def init_queue() -> None:
    global _pool
    _pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def close_queue() -> None:
    if _pool is not None:
        await _pool.aclose()


async def enqueue(job_id: str) -> None:
    if _pool is None:
        raise RuntimeError("job queue not initialised")
    await _pool.enqueue_job(WORKER_FUNCTION, job_id)


async def _worker_alive(job_id: str) -> bool:
    """Is a worker still actually processing this job?

    A job stuck at 'running' with no heartbeat means the worker died - the
    container was restarted, the laptop slept, CUDA blew up. Without this check
    such a job can never be retried, because it looks busy forever.
    """
    if _pool is None:
        return False
    try:
        return await _pool.exists(HEARTBEAT_KEY.format(job_id)) > 0
    except Exception:
        log.warning("could not read heartbeat for %s; assuming alive", job_id,
                    exc_info=True)
        return True


async def create_job_from_upload(job_id: str, filename: str, path: Path) -> None:
    title = Path(filename).stem.replace("_", " ").strip() or filename
    db.execute(
        "INSERT INTO jobs (id, title, original_filename, original_path, size_bytes,"
        " status, progress, options, created_at, updated_at)"
        " VALUES (?,?,?,?,?, 'queued', 0, ?, ?, ?)",
        (job_id, title, filename, str(path), path.stat().st_size,
         json.dumps({"summarize": True}), db.now(), db.now()),
    )
    await enqueue(job_id)


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
class JobPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    service_date: str | None = None


def _serialize(row: Any) -> dict[str, Any]:
    job = db.row_to_job(row)
    directory = job_dir(job["id"])
    job["has_audio"] = (directory / "audio.opus").exists()
    job["has_peaks"] = (directory / "peaks.json").exists()
    job["has_transcript"] = (directory / "transcript.json").exists()
    job["has_summary"] = (directory / "summary.json").exists()
    # The music stage always writes this file, so its absence is what tells the
    # list apart from an imported job - the transcript's own "source" marker is
    # too expensive to read for every row.
    job["has_music"] = (directory / "music.json").exists()
    # Imported jobs keep only the Opus proxy by default, so the UI must not
    # offer a download that would 404.
    job["has_original"] = bool(job["original_path"]) and Path(job["original_path"]).exists()
    return job


def _require(job_id: str) -> Any:
    row = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if row is None:
        raise HTTPException(404, "Job nicht gefunden")
    return row


@router.get("")
async def list_jobs() -> dict[str, Any]:
    rows = db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 500")
    return {"jobs": [_serialize(r) for r in rows], "stages": STAGES}


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    return _serialize(_require(job_id))


@router.patch("/{job_id}")
async def patch_job(job_id: str, payload: JobPatch) -> dict[str, Any]:
    _require(job_id)
    fields = payload.model_dump(exclude_unset=True)
    if fields:
        db.update_row("jobs", job_id, **fields)
    return _serialize(_require(job_id))


class JobImport(BaseModel):
    """A job whose transcript already exists and must not be reprocessed."""
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str = Field(max_length=300)
    original_filename: str
    service_date: str | None = None
    original_path: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    created_at: str | None = None


@router.post("/import")
async def import_job(payload: JobImport) -> dict[str, Any]:
    """Register an already-transcribed recording.

    The importer runs in the worker container because it needs ffmpeg, but the
    API is the only process allowed to write SQLite - hence this endpoint rather
    than the worker touching the database. Re-running an import updates the row
    instead of duplicating it, so the whole batch is safe to repeat.
    """
    existing = db.query_one("SELECT id FROM jobs WHERE id = ?", (payload.id,))
    fields = payload.model_dump(exclude={"id"}, exclude_none=True)
    created = fields.pop("created_at", None) or db.now()

    if existing:
        db.update_row("jobs", payload.id, status="done", progress=1.0, stage=None,
                      error=None, message=None, **fields)
    else:
        db.execute(
            "INSERT INTO jobs (id, title, service_date, original_filename,"
            " original_path, size_bytes, duration_s, status, progress, options,"
            " created_at, updated_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?, 'done', 1.0, ?, ?, ?, ?)",
            (payload.id, payload.title, payload.service_date,
             payload.original_filename, payload.original_path, payload.size_bytes,
             payload.duration_s, json.dumps({"imported": True}),
             created, db.now(), db.now()),
        )
    return _serialize(_require(payload.id))


@router.delete("/{job_id}")
async def delete_job(job_id: str) -> dict[str, str]:
    _require(job_id)
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return {"status": "deleted"}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str) -> dict[str, Any]:
    row = _require(job_id)
    if row["status"] == "running" and await _worker_alive(job_id):
        raise HTTPException(409, "Job laeuft bereits")
    db.update_row("jobs", job_id, status="queued", stage=None, progress=0,
                  error=None, message=None, finished_at=None)
    await enqueue(job_id)
    return _serialize(_require(job_id))


# --------------------------------------------------------------------------
# Progress stream
# --------------------------------------------------------------------------
@router.get("/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    _require(job_id)
    queue = bus.subscribe(job_id)

    async def stream():
        try:
            # Snapshot first, so a browser that connects late is never stuck on
            # a stale view waiting for the next event.
            yield _sse(_serialize(_require(job_id)))
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # keeps the tunnel from idling us out
                    continue
                yield _sse(event)
                if event.get("status") in {"done", "failed", "canceled"}:
                    yield _sse(_serialize(_require(job_id)))
                    break
        finally:
            bus.unsubscribe(job_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Without this the tunnel/proxy buffers the stream and progress
            # arrives all at once at the end.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


# --------------------------------------------------------------------------
# Media
# --------------------------------------------------------------------------
@router.get("/{job_id}/peaks")
async def get_peaks(job_id: str) -> FileResponse:
    _require(job_id)
    directory = job_dir(job_id)
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    # The worker writes both; the gzipped copy is ~10x smaller over the tunnel.
    gz_path = directory / "peaks.json.gz"
    if gz_path.exists():
        return FileResponse(gz_path, media_type="application/json",
                            headers={**headers, "Content-Encoding": "gzip"})
    path = directory / "peaks.json"
    if not path.exists():
        raise HTTPException(404, "Wellenform noch nicht berechnet")
    return FileResponse(path, media_type="application/json", headers=headers)


@router.get("/{job_id}/audio")
async def get_audio(job_id: str) -> FileResponse:
    """The 48 kbps Opus proxy. Never the original -- that would defeat the point."""
    _require(job_id)
    path = job_dir(job_id) / "audio.opus"
    if not path.exists():
        raise HTTPException(404, "Audio noch nicht aufbereitet")
    # FileResponse handles Range requests, which is what lets the player seek
    # without downloading the whole file.
    return FileResponse(path, media_type="audio/ogg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable",
                                 "Accept-Ranges": "bytes"})


@router.get("/{job_id}/original")
async def get_original(job_id: str) -> FileResponse:
    row = _require(job_id)
    # Imported jobs keep no original. Guard on is_file() rather than exists():
    # Path("") is Path("."), which exists, and serving a directory is a 500.
    if not row["original_path"]:
        raise HTTPException(404, "Fuer diese Aufnahme wurde keine Originaldatei gespeichert")
    path = Path(row["original_path"])
    if not path.is_file():
        raise HTTPException(404, "Originaldatei nicht gefunden")
    return FileResponse(path, filename=row["original_filename"])
