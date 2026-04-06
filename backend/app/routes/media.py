import mimetypes
import os

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.session import Session

log = structlog.get_logger()
router = APIRouter(prefix="/v1/media", tags=["media"])


@router.get("/{session_id}")
async def serve_media(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session or not session.audio_file_path:
        raise HTTPException(status_code=404, detail="Media not found")

    file_path = session.audio_file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    media_type, _ = mimetypes.guess_type(file_path)
    return FileResponse(
        file_path,
        media_type=media_type or "application/octet-stream",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{session_id}/thumbnail")
async def serve_thumbnail(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session or not session.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    if not os.path.exists(session.thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return FileResponse(session.thumbnail_path, media_type="image/jpeg")
