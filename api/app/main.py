"""Transkript API.

Authentication is deliberately absent: the whole hostname sits behind Cloudflare
Access, so anything that reaches this process has already been authenticated at
the edge. Never expose this port beyond 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from . import db, exports, jobs, transcript, uploads
from .config import (LOG_LEVEL, REDIS_URL, STATIC_DIR, UPLOAD_EXPIRY_HOURS,
                     UPLOADS_DIR, ensure_dirs)
from .events import HEARTBEAT_KEY, WRITABLE_EVENT_FIELDS, bus

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("transcribe.api")


def sweep_stale_uploads() -> int:
    """Drop part-files from uploads that were abandoned mid-transfer."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=UPLOAD_EXPIRY_HOURS)).isoformat()
    stale = db.query(
        "SELECT * FROM uploads WHERE job_id IS NULL AND updated_at < ?", (cutoff,)
    )
    for row in stale:
        Path(row["path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM uploads WHERE id = ?", (row["id"],))
    # Orphaned part files with no DB row at all (e.g. after a data reset).
    known = {Path(r["path"]).name for r in db.query("SELECT path FROM uploads")}
    for orphan in UPLOADS_DIR.glob("*.part"):
        if orphan.name not in known:
            orphan.unlink(missing_ok=True)
    return len(stale)


async def reconcile_running_jobs() -> int:
    """Work out what happened to jobs that were 'running' when we last stopped.

    The API restarting does not mean the *worker* restarted, so a running job is
    only failed when its heartbeat is gone. Otherwise the worker still owns it
    and the last heartbeat carries the state we missed while we were down.
    """
    rows = db.query("SELECT id FROM jobs WHERE status = 'running'")
    if not rows:
        return 0

    failed = 0
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        for row in rows:
            job_id = row["id"]
            raw = await client.get(HEARTBEAT_KEY.format(job_id))
            if raw is None:
                db.update_row(
                    "jobs", job_id, status="failed",
                    error="Verarbeitung wurde unterbrochen (Neustart des Servers).",
                    finished_at=db.now(),
                )
                failed += 1
                continue
            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                continue
            fields = {k: v for k, v in state.items() if k in WRITABLE_EVENT_FIELDS}
            if fields:
                db.update_row("jobs", job_id, **fields)
            log.info("job %s is still running on the worker; resynced from heartbeat",
                     job_id)
    finally:
        await client.aclose()
    return failed


RECONCILE_INTERVAL_S = 60


async def _reconcile_loop() -> None:
    """Keep checking for jobs whose worker died.

    Doing this only at startup is not enough: the worker container can be
    restarted, OOM, or be interrupted by the laptop sleeping while the API stays
    up the whole time. Without this the job spins in the UI forever and cannot
    even be retried.
    """
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL_S)
        try:
            failed = await reconcile_running_jobs()
            if failed:
                log.warning("marked %d job(s) failed: worker heartbeat gone", failed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reconcile pass failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.connect()
    swept = sweep_stale_uploads()
    interrupted = await reconcile_running_jobs()
    if swept or interrupted:
        log.info("startup cleanup: %d stale uploads, %d interrupted jobs", swept, interrupted)
    await jobs.init_queue()
    await bus.start()
    reconciler = asyncio.create_task(_reconcile_loop(), name="reconciler")
    log.info("transcribe api ready")
    try:
        yield
    finally:
        reconciler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reconciler
        await bus.stop()
        await jobs.close_queue()


app = FastAPI(title="Transkript", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(transcript.router)
app.include_router(exports.router)


@app.get("/api/health")
async def health() -> dict[str, object]:
    counts = {
        row["status"]: row["n"]
        for row in db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }
    return {"status": "ok", "jobs": counts}


# --- SPA --------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        # Anything under these prefixes is API surface; a miss there is a real
        # 404, not a client-side route.
        if path.startswith(("api/", "files")):
            raise HTTPException(404, "Not found")
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:  # pragma: no cover - only hit when running the API without a built SPA
    @app.get("/")
    async def missing_ui() -> JSONResponse:
        return JSONResponse({"detail": "UI not built"}, status_code=503)
