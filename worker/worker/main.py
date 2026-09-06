"""arq worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

from . import pipeline
from .config import ASR_MODEL, LLM_ENABLED, LOG_LEVEL, REDIS_URL

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("transcribe.worker")


async def transcribe_job(ctx: dict, job_id: str) -> dict:
    # The pipeline is synchronous and GPU-bound; run it off the event loop so
    # arq can still answer health checks while a 90-minute service is grinding.
    return await asyncio.to_thread(pipeline.process, job_id)


async def startup(ctx: dict) -> None:
    import torch
    from .config import HF_TOKEN

    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU (no GPU!)"
    log.info("worker ready on %s | asr=%s | summary=%s",
             device, ASR_MODEL, "on" if LLM_ENABLED else "off")
    if not HF_TOKEN:
        log.error(
            "HF_TOKEN is not set. Diarization will fail. Create a token at "
            "https://hf.co/settings/tokens, accept the terms at "
            "https://hf.co/pyannote/speaker-diarization-community-1, then put it "
            "in .env and restart."
        )


class WorkerSettings:
    functions = [transcribe_job]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    on_startup = startup

    # One job at a time. This is the whole VRAM strategy: two concurrent jobs
    # would not fit in 8 GB no matter how the stages are ordered.
    max_jobs = 1
    job_timeout = 6 * 3600
    keep_result = 3600
    # No automatic retry - a failure here is an OOM or a bad file, and retrying
    # immediately just burns another hour. The UI offers an explicit retry.
    max_tries = 1
