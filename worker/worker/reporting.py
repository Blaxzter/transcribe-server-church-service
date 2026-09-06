"""Progress reporting from worker to API over Redis pub/sub.

The pipeline stages are synchronous and run in a thread, so this uses the plain
(sync) redis client rather than the async one arq holds.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import redis

from .config import EVENTS_CHANNEL, REDIS_URL

log = logging.getLogger(__name__)

# Rough share of total wall-clock per stage on the target GPU. Only used to turn
# per-stage progress into one honest overall number for the UI.
STAGE_WEIGHTS: dict[str, float] = {
    "normalize": 0.06,
    "peaks": 0.02,
    "music": 0.12,
    "vad": 0.02,
    "asr": 0.40,
    "align": 0.06,
    "diarize": 0.24,
    "merge": 0.02,
    "summarize": 0.06,
}

STAGE_LABELS: dict[str, str] = {
    "normalize": "Audio wird aufbereitet",
    "peaks": "Wellenform wird berechnet",
    "music": "Musik wird erkannt",
    "vad": "Sprache wird gesucht",
    "asr": "Text wird erkannt",
    "align": "Zeitstempel werden verfeinert",
    "diarize": "Sprecher werden unterschieden",
    "merge": "Transkript wird zusammengesetzt",
    "summarize": "Zusammenfassung wird erstellt",
}

_MIN_PUBLISH_INTERVAL = 0.25

# Liveness. The API restarting mid-job must be able to tell "the worker is still
# grinding" from "the worker died", so a background thread refreshes a
# short-lived key while the job runs. The interval has to stay well under the
# TTL, and both have to survive a multi-minute model download with no progress
# events at all.
HEARTBEAT_KEY = "transcribe:job:{}:alive"
HEARTBEAT_INTERVAL_S = 15
HEARTBEAT_TTL_S = 90


class Reporter:
    def __init__(self, job_id: str, *, skip: set[str] | None = None) -> None:
        self.job_id = job_id
        self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self._skip = skip or set()
        self._current: str | None = None
        self._last_publish = 0.0
        self._last_state: dict[str, Any] = {}
        self._stop_heartbeat = threading.Event()
        self._heartbeat: threading.Thread | None = None

        active = {k: v for k, v in STAGE_WEIGHTS.items() if k not in self._skip}
        total = sum(active.values()) or 1.0
        self._weights = {k: v / total for k, v in active.items()}
        # Cumulative progress at the point each stage begins.
        self._offsets: dict[str, float] = {}
        running = 0.0
        for name in STAGE_WEIGHTS:
            if name in self._weights:
                self._offsets[name] = running
                running += self._weights[name]

    # -- publishing --------------------------------------------------------
    def _publish(self, payload: dict[str, Any], *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < _MIN_PUBLISH_INTERVAL:
            return
        self._last_publish = now
        payload["job_id"] = self.job_id
        self._last_state = {**self._last_state, **payload}
        try:
            self._redis.publish(EVENTS_CHANNEL, json.dumps(payload, ensure_ascii=False,
                                                           default=str))
        except redis.RedisError:
            log.warning("could not publish progress for %s", self.job_id, exc_info=True)

    # -- liveness ----------------------------------------------------------
    def _beat(self) -> None:
        while not self._stop_heartbeat.wait(HEARTBEAT_INTERVAL_S):
            try:
                self._redis.setex(HEARTBEAT_KEY.format(self.job_id), HEARTBEAT_TTL_S,
                                  json.dumps(self._last_state, default=str))
            except redis.RedisError:
                log.warning("heartbeat failed for %s", self.job_id, exc_info=True)

    def start(self) -> None:
        state = {"status": "running", "progress": 0.0, "stage": None,
                 "error": None, "message": "Job wird gestartet",
                 "started_at": _utcnow()}
        try:
            self._redis.setex(HEARTBEAT_KEY.format(self.job_id), HEARTBEAT_TTL_S,
                              json.dumps(state, default=str))
        except redis.RedisError:
            log.warning("could not set initial heartbeat", exc_info=True)
        self._heartbeat = threading.Thread(target=self._beat, daemon=True,
                                           name=f"heartbeat-{self.job_id[:8]}")
        self._heartbeat.start()
        self._publish(state, force=True)

    def stage(self, name: str, message: str | None = None) -> None:
        self._current = name
        self._publish({"status": "running", "stage": name,
                       "progress": round(self._offsets.get(name, 0.0), 4),
                       "message": message or STAGE_LABELS.get(name, name)}, force=True)

    def progress(self, fraction: float, message: str | None = None) -> None:
        """`fraction` is progress *within* the current stage, 0..1."""
        if self._current is None:
            return
        fraction = min(max(fraction, 0.0), 1.0)
        overall = self._offsets.get(self._current, 0.0) + \
            self._weights.get(self._current, 0.0) * fraction
        payload: dict[str, Any] = {"status": "running", "stage": self._current,
                                   "progress": round(overall, 4)}
        if message:
            payload["message"] = message
        self._publish(payload)

    def finished(self, **fields: Any) -> None:
        self._publish({"status": "done", "progress": 1.0, "stage": None, "error": None,
                       "message": "Fertig", "finished_at": _utcnow(), **fields},
                      force=True)

    def failed(self, error: str) -> None:
        self._publish({"status": "failed", "stage": self._current, "error": error[:2000],
                       "message": "Fehlgeschlagen", "finished_at": _utcnow()}, force=True)

    def close(self) -> None:
        self._stop_heartbeat.set()
        if self._heartbeat:
            self._heartbeat.join(timeout=2)
        try:
            # Clear liveness explicitly: the job is over either way, and leaving
            # the key to expire would make a restarted API wait 90s to find out.
            self._redis.delete(HEARTBEAT_KEY.format(self.job_id))
        except redis.RedisError:  # pragma: no cover - best effort
            pass
        try:
            self._redis.close()
        except Exception:  # pragma: no cover - best effort
            pass


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
