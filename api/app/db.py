"""SQLite access.

The API container is the *only* writer. The worker never touches this file; it
reports back over Redis and the event listener in `events.py` applies those
updates here. That keeps us to a single writer and avoids SQLite locking
pathologies on a WSL2 bind mount.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH, ensure_dirs

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    service_date      TEXT,
    original_filename TEXT NOT NULL,
    original_path     TEXT,
    size_bytes        INTEGER,
    duration_s        REAL,
    status            TEXT NOT NULL DEFAULT 'queued',
    stage             TEXT,
    progress          REAL NOT NULL DEFAULT 0,
    message           TEXT,
    error             TEXT,
    preset            TEXT NOT NULL DEFAULT 'soundboard',
    options           TEXT NOT NULL DEFAULT '{}',
    speaker_count     INTEGER,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT
);

CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS uploads (
    id            TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    filename      TEXT NOT NULL,
    length_bytes  INTEGER NOT NULL,
    offset_bytes  INTEGER NOT NULL DEFAULT 0,
    metadata      TEXT,
    job_id        TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            ensure_dirs()
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.execute("PRAGMA busy_timeout=5000")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> None:
    with _lock:
        conn = connect()
        conn.execute(sql, params)
        conn.commit()


def update_row(table: str, row_id: str, **fields: Any) -> None:
    """Patch a row, always bumping updated_at. Unknown/None-only calls are no-ops."""
    fields = {k: v for k, v in fields.items() if v is not _UNSET}
    if not fields:
        return
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*fields.values(), row_id))


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


_UNSET = _Unset()
UNSET: Any = _UNSET


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    try:
        job["options"] = json.loads(job.get("options") or "{}")
    except json.JSONDecodeError:
        job["options"] = {}
    return job
