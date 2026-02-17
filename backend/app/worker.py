"""arq worker for background pipeline processing.

Start with:
    arq app.worker.WorkerSettings
"""

import structlog
from arq.connections import RedisSettings

from app.config import settings
from app.db import async_session
from app.services.pipeline import PipelineOrchestrator

log = structlog.get_logger()


async def process_clip(ctx: dict, session_id: str) -> dict:
    """Process a clip through the full pipeline."""
    log.info("worker_process_clip_start", session_id=session_id)

    async with async_session() as db:
        orchestrator = PipelineOrchestrator(db)
        await orchestrator.process_clip(session_id)

    log.info("worker_process_clip_done", session_id=session_id)
    return {"session_id": session_id, "status": "done"}


class WorkerSettings:
    functions = [process_clip]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 3
    job_timeout = 600  # 10 minutes per clip
