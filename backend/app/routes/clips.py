import asyncio
import os
import subprocess
from datetime import datetime
from glob import glob

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# from app.auth import require_admin  # upload open to all users
from app.config import settings
from app.db import async_session, get_db
from app.models.claim import Claim
from app.models.session import Session
# from app.models.user import User  # unused after removing admin gate
from app.schemas.session import ClipStatusResponse, ClipUploadResponse

log = structlog.get_logger()

router = APIRouter(prefix="/v1/clips", tags=["clips"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".mov", ".mkv", ".ogg", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv"}
MAX_SIZE = settings.max_upload_size_mb * 1024 * 1024


def _is_youtube_url(url: str) -> bool:
    return any(domain in url.lower() for domain in ["youtube.com", "youtu.be", "youtube-nocookie.com"])


def _populate_media_metadata(session: Session, file_path: str) -> None:
    session.audio_file_path = file_path
    ext = os.path.splitext(file_path)[1].lower()
    session.media_type = "video" if ext in VIDEO_EXTENSIONS else "audio"


def _maybe_generate_thumbnail(session: Session, file_path: str) -> None:
    if session.media_type != "video":
        return

    thumb_path = os.path.join(settings.upload_dir, f"{session.id}_thumb.jpg")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                file_path,
                "-ss",
                "2",
                "-frames:v",
                "1",
                "-s",
                "320x180",
                "-y",
                thumb_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if os.path.exists(thumb_path):
            session.thumbnail_path = thumb_path
    except Exception as e:
        log.warning("thumbnail_generation_failed", session_id=session.id, error=str(e))


def _resolve_downloaded_file(download_base: str) -> str | None:
    for path in sorted(glob(f"{download_base}.*")):
        ext = os.path.splitext(path)[1].lower()
        if ext in ALLOWED_EXTENSIONS:
            return path
    return None


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

    _populate_media_metadata(session, file_path)
    _maybe_generate_thumbnail(session, file_path)
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


async def _download_and_process_url(session_id: str, source_url: str) -> None:
    """Download from URL then run pipeline, all in background."""
    async with async_session() as db:
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            return

        download_base = os.path.join(settings.upload_dir, session_id)

        async def _run_ytdlp(args: list[str]) -> tuple[int, str, str]:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            return proc.returncode if proc.returncode is not None else 1, stdout.decode(), stderr.decode()

        try:
            actual_path = None
            # Download video capped at 720p to keep file sizes reasonable
            # Use browser cookies so YouTube doesn't block with bot detection
            rc, _, stderr_out = await _run_ytdlp([
                "yt-dlp",
                "--no-playlist",
                "--cookies-from-browser", "chrome",
                "--remote-components", "ejs:github",
                "--remote-components", "ejs:npm",
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
                "--merge-output-format", "mp4",
                "-o", f"{download_base}.%(ext)s",
                source_url,
            ])
            log.info("ytdlp_attempt_1", rc=rc, stderr=stderr_out[:200] if stderr_out else "")
            if rc == 0:
                actual_path = _resolve_downloaded_file(download_base)

            # Broader video fallback
            if actual_path is None:
                rc, _, stderr_out = await _run_ytdlp([
                    "yt-dlp",
                    "--no-playlist",
                    "--cookies-from-browser", "chrome",
                "--remote-components", "ejs:github",
                "--remote-components", "ejs:npm",
                    "-f", "bv*[height<=720]+ba/b[height<=720]/bv+ba/b",
                    "--merge-output-format", "mp4",
                    "-o", f"{download_base}.%(ext)s",
                    source_url,
                ])
                log.info("ytdlp_attempt_2", rc=rc, stderr=stderr_out[:200] if stderr_out else "")
                if rc == 0:
                    actual_path = _resolve_downloaded_file(download_base)

            if actual_path is None:
                session.status = "error"
                session.error_message = "Failed to download media from URL"
                await db.commit()
                return

            _populate_media_metadata(session, actual_path)
            _maybe_generate_thumbnail(session, actual_path)
            session.processing_stage = "downloading"
            await db.commit()
        except Exception as e:
            session.status = "error"
            session.error_message = f"Download failed: {str(e)[:200]}"
            await db.commit()
            return

    # Now run the pipeline
    from app.services.pipeline import PipelineOrchestrator

    async with async_session() as db:
        orchestrator = PipelineOrchestrator(db)
        await orchestrator.process_clip(session_id)


@router.post("/url", response_model=ClipUploadResponse, status_code=202)
async def upload_from_url(
    background_tasks: BackgroundTasks,
    source_url: str = Form(...),
    title: str | None = Form(None),
    channel_name: str | None = Form(None),
    language: str = Form("en"),
    db: AsyncSession = Depends(get_db),
):
    os.makedirs(settings.upload_dir, exist_ok=True)
    session = Session(
        title=title or source_url,
        source_url=source_url,
        channel_name=channel_name,
        language=language,
        status="queued",
        processing_stage="downloading",
    )
    db.add(session)
    await db.commit()

    background_tasks.add_task(_download_and_process_url, session.id, source_url)
    log.info("clip_url_upload_enqueued", session_id=session.id, source_url=source_url)

    return ClipUploadResponse(
        clip_id=session.id,
        status="queued",
        estimated_processing_seconds=120,
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
