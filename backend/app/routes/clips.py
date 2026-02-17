import os
from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session, get_db
from app.models.claim import Claim
from app.models.session import Session
from app.schemas.session import ClipStatusResponse, ClipUploadResponse

log = structlog.get_logger()

router = APIRouter(prefix="/v1/clips", tags=["clips"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac"}
MAX_SIZE = settings.max_upload_size_mb * 1024 * 1024


async def _run_pipeline_background(session_id: str) -> None:
    """Run the pipeline in a background task with its own DB session."""
    from app.services.pipeline import PipelineOrchestrator

    async with async_session() as db:
        orchestrator = PipelineOrchestrator(db)
        await orchestrator.process_clip(session_id)


@router.post("", response_model=ClipUploadResponse, status_code=202)
async def upload_clip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    source_url: str | None = Form(None),
    channel_name: str | None = Form(None),
    broadcast_date: str | None = Form(None),
    language: str = Form("en"),
    db: AsyncSession = Depends(get_db),
):
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Save uploaded file
    os.makedirs(settings.upload_dir, exist_ok=True)
    session = Session(
        title=title,
        source_url=source_url,
        channel_name=channel_name,
        language=language,
        status="queued",
        processing_stage=None,
    )
    if broadcast_date:
        session.broadcast_date = datetime.fromisoformat(broadcast_date)

    db.add(session)
    await db.flush()

    # Save file with session ID
    file_path = os.path.join(settings.upload_dir, f"{session.id}{ext}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max {settings.max_upload_size_mb}MB.")

    with open(file_path, "wb") as f:
        f.write(content)

    session.audio_file_path = file_path
    await db.commit()

    # Enqueue pipeline processing as a background task
    background_tasks.add_task(_run_pipeline_background, session.id)
    log.info("clip_upload_enqueued", session_id=session.id)

    return ClipUploadResponse(
        clip_id=session.id,
        status="queued",
        estimated_processing_seconds=60,
        status_url=f"/v1/clips/{session.id}/status",
    )


@router.post("/{clip_id}/process")
async def process_clip_sync(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Process a clip synchronously. Useful for testing without the background worker."""
    from app.services.pipeline import PipelineOrchestrator

    result = await db.execute(select(Session).where(Session.id == clip_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Clip not found")
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Clip already processed")
    if session.status == "processing":
        raise HTTPException(status_code=409, detail="Clip is currently processing")

    orchestrator = PipelineOrchestrator(db)
    await orchestrator.process_clip(clip_id)

    # Refresh session state
    await db.refresh(session)
    claims_result = await db.execute(select(Claim).where(Claim.session_id == clip_id))
    claims = claims_result.scalars().all()

    return {
        "clip_id": clip_id,
        "status": session.status,
        "claims_detected": len(claims),
        "claims_verdicted": sum(1 for c in claims if c.verdict_label is not None),
        "error": session.error_message,
    }


@router.get("/{clip_id}/status", response_model=ClipStatusResponse)
async def get_clip_status(clip_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == clip_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Count claims
    claims_result = await db.execute(
        select(Claim).where(Claim.session_id == clip_id)
    )
    claims = claims_result.scalars().all()
    claims_detected = len(claims)
    claims_verdicted = sum(1 for c in claims if c.verdict_label is not None)

    return ClipStatusResponse(
        clip_id=session.id,
        status=session.status,
        stage=session.processing_stage,
        progress_pct=session.progress_pct,
        claims_detected=claims_detected,
        claims_verdicted=claims_verdicted,
        error=session.error_message,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )
