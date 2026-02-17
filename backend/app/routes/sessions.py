from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.claim import Claim
from app.models.session import Session, TranscriptSegment
from app.schemas.session import SessionResponse, TranscriptSegmentResponse

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("/{session_id}/transcript", response_model=list[TranscriptSegmentResponse])
async def get_transcript(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_ms)
    )
    segments = result.scalars().all()
    return [
        TranscriptSegmentResponse(
            segment_id=s.id,
            speaker_label=s.speaker_label,
            text=s.text,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
        )
        for s in segments
    ]


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .order_by(Session.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    sessions = result.scalars().all()

    responses = []
    for s in sessions:
        claim_count = (
            await db.execute(
                select(func.count()).where(Claim.session_id == s.id)
            )
        ).scalar() or 0

        responses.append(
            SessionResponse(
                session_id=s.id,
                title=s.title,
                status=s.status,
                duration_seconds=s.duration_seconds,
                claims_count=claim_count,
                created_at=s.created_at,
            )
        )
    return responses
