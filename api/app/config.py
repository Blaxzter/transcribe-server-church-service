"""Runtime configuration, read once from the environment."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
UPLOADS_DIR = DATA_DIR / "uploads"
# Word templates for the DOCX export, one .docx per row in the templates table.
TEMPLATES_DIR = DATA_DIR / "templates"
DB_PATH = DATA_DIR / "transcribe.db"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
EVENTS_CHANNEL = "transcribe:events"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# 8 GiB default. Cloudflare caps a single *request* at 100 MB, which is why uploads
# are chunked; this is the cap on the assembled file.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 8 * 1024**3))

# Uploads with no PATCH activity for this long are considered abandoned.
UPLOAD_EXPIRY_HOURS = 48

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts",
}


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def ensure_dirs() -> None:
    for d in (DATA_DIR, JOBS_DIR, UPLOADS_DIR, TEMPLATES_DIR):
        d.mkdir(parents=True, exist_ok=True)
