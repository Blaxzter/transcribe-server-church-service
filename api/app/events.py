"""Fan-out of worker progress events.

The worker publishes JSON events onto a single Redis channel. One listener task
in this process (a) applies them to SQLite -- keeping the API as the sole DB
writer -- and (b) pushes them onto per-job asyncio queues that the SSE endpoint
drains.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from redis.asyncio import Redis

from . import db
from .config import EVENTS_CHANNEL, REDIS_URL

log = logging.getLogger(__name__)

# Columns a worker event is allowed to write. Anything else is ignored so a
# malformed event can never corrupt the jobs table.
WRITABLE_EVENT_FIELDS = {
    "status", "stage", "progress", "message", "error",
    "duration_s", "speaker_count", "started_at", "finished_at",
}

# Must match worker/worker/reporting.py. The worker refreshes this key while a
# job runs so a restarted API can tell "still working" from "worker died".
HEARTBEAT_KEY = "transcribe:job:{}:alive"

TERMINAL = {"done", "failed", "canceled"}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._task: asyncio.Task | None = None
        self._redis: Redis | None = None

    # -- subscription ------------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id)
        if not subs:
            return
        subs.discard(queue)
        if not subs:
            self._subscribers.pop(job_id, None)

    def _fan_out(self, job_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled browser must not block the listener.
                log.warning("dropping event for %s: subscriber queue full", job_id)

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        self._redis = Redis.from_url(REDIS_URL, decode_responses=True)
        self._task = asyncio.create_task(self._listen(), name="event-listener")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._redis:
            await self._redis.aclose()

    async def _listen(self) -> None:
        assert self._redis is not None
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(EVENTS_CHANNEL)
                log.info("listening on %s", EVENTS_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        event = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        log.warning("ignoring non-JSON event")
                        continue
                    self._handle(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event listener crashed, retrying in 2s")
                await asyncio.sleep(2)

    def _handle(self, event: dict[str, Any]) -> None:
        job_id = event.get("job_id")
        if not job_id:
            return
        fields = {k: v for k, v in event.items() if k in WRITABLE_EVENT_FIELDS}
        if fields:
            if fields.get("status") in TERMINAL and "finished_at" not in fields:
                fields["finished_at"] = db.now()
            try:
                db.update_row("jobs", job_id, **fields)
            except Exception:
                log.exception("failed to persist event for %s", job_id)
        self._fan_out(job_id, event)


bus = EventBus()
