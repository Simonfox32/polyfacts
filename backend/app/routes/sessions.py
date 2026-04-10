import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db import get_db
from app.models.claim import Claim, EvidencePassage, Source
from app.models.session import Session, TranscriptSegment
from app.models.user import User
from app.schemas.session import (
    SessionDetailResponse,
    SessionResponse,
    TranscriptSegmentResponse,
)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class UpdateSessionRequest(PydanticBaseModel):
    title: str | None = None
    description: str | None = None


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
        claims = (await db.execute(select(Claim).where(Claim.session_id == s.id))).scalars().all()
        verdict_distribution: dict[str, int] = {}
        for claim in claims:
            label = claim.verdict_label or "UNVERIFIED"
            verdict_distribution[label] = verdict_distribution.get(label, 0) + 1

        responses.append(
            SessionResponse(
                session_id=s.id,
                title=s.title,
                status=s.status,
                channel_name=s.channel_name,
                duration_seconds=s.duration_seconds,
                media_type=getattr(s, "media_type", "audio"),
                view_count=s.view_count,
                claims_count=len(claims),
                verdict_distribution=verdict_distribution,
                thumbnail_url=f"/v1/media/{s.id}/thumbnail" if s.thumbnail_path else None,
                created_at=s.created_at,
            )
        )
    return responses


@router.post("/{session_id}/view")
async def record_view(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("UPDATE sessions SET view_count = view_count + 1 WHERE id = :sid RETURNING view_count"),
        {"sid": session_id},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return {"view_count": row[0]}


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    claims = (
        await db.execute(select(Claim).where(Claim.session_id == session_id))
    ).scalars().all()

    verdict_distribution: dict[str, int] = {}
    speakers = set()
    for claim in claims:
        label = claim.verdict_label or "UNVERIFIED"
        verdict_distribution[label] = verdict_distribution.get(label, 0) + 1
        if claim.speaker_label:
            speakers.add(claim.speaker_label)

    # Also collect speakers from transcript segments
    transcript_speakers = (
        await db.execute(
            select(TranscriptSegment.speaker_label)
            .where(TranscriptSegment.session_id == session_id)
            .distinct()
        )
    ).scalars().all()
    for sp in transcript_speakers:
        if sp:
            speakers.add(sp)

    return SessionDetailResponse(
        session_id=session.id,
        title=session.title,
        description=session.description,
        status=session.status,
        channel_name=session.channel_name,
        broadcast_date=session.broadcast_date,
        duration_seconds=session.duration_seconds,
        media_type=getattr(session, "media_type", "audio"),
        view_count=session.view_count,
        claims_count=len(claims),
        speakers=sorted(speakers),
        verdict_distribution=verdict_distribution,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


@router.patch("/{session_id}", status_code=200)
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update session title and/or description. Admin only."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.title is not None:
        session.title = body.title.strip()
    if body.description is not None:
        session.description = body.description.strip()

    await db.commit()
    await db.refresh(session)
    return {
        "session_id": session.id,
        "title": session.title,
        "description": session.description,
    }


@router.get("/{session_id}/sources")
async def get_session_sources(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get all unique sources used across all claims in a session, grouped by tier."""
    query = (
        select(Source)
        .join(EvidencePassage, EvidencePassage.source_id == Source.id)
        .join(Claim, Claim.id == EvidencePassage.claim_id)
        .where(Claim.session_id == session_id)
        .distinct()
    )
    result = await db.execute(query)
    sources = result.scalars().all()

    grouped: dict[str, list[dict[str, str | None]]] = {}
    for source in sources:
        tier = source.source_tier or "tier_5_other"
        if tier not in grouped:
            grouped[tier] = []
        grouped[tier].append(
            {
                "source_id": source.id,
                "url": source.url,
                "title": source.title,
                "publisher": source.publisher,
                "source_tier": tier,
                "publication_date": (
                    source.publication_date.isoformat() if source.publication_date else None
                ),
            }
        )

    tier_order = [
        "tier_1_government_primary",
        "tier_2_court_academic",
        "tier_3_major_outlet",
        "tier_4_regional_specialty",
        "tier_5_other",
    ]
    sorted_groups = []
    for tier in tier_order:
        if tier in grouped:
            parts = tier.split("_", 2)
            display_name = parts[2].replace("_", " ").title() if len(parts) > 2 else tier
            sorted_groups.append(
                {
                    "tier": tier,
                    "display_name": display_name,
                    "sources": grouped[tier],
                }
            )

    return {"groups": sorted_groups, "total_sources": len(sources)}


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


class RenameSpeakerRequest(PydanticBaseModel):
    old_name: str
    new_name: str


@router.put("/{session_id}/speakers")
async def rename_speaker(
    session_id: str,
    body: RenameSpeakerRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Rename a speaker across all transcript segments and claims for a session."""
    # Update transcript segments
    await db.execute(
        text(
            "UPDATE transcript_segments SET speaker_label = :new_name "
            "WHERE session_id = :sid AND speaker_label = :old_name"
        ),
        {"new_name": body.new_name, "old_name": body.old_name, "sid": session_id},
    )
    # Update claims
    await db.execute(
        text(
            "UPDATE claims SET speaker_label = :new_name "
            "WHERE session_id = :sid AND speaker_label = :old_name"
        ),
        {"new_name": body.new_name, "old_name": body.old_name, "sid": session_id},
    )
    await db.commit()
    return {"status": "ok", "old_name": body.old_name, "new_name": body.new_name}


@router.delete("/{session_id}", status_code=200)
async def delete_session(
    session_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a session and all related data. Admin only."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    for path in [session.audio_file_path, session.thumbnail_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    # Delete related records that lack ON DELETE CASCADE
    from app.models.claim import Claim, EvidencePassage, VerdictAuditLog
    from app.models.session import TranscriptSegment

    # Get claim IDs for this session
    claim_ids_result = await db.execute(
        select(Claim.id).where(Claim.session_id == session_id)
    )
    claim_ids = [r[0] for r in claim_ids_result.all()]

    if claim_ids:
        # Delete evidence passages and audit logs referencing these claims
        await db.execute(
            delete(EvidencePassage).where(EvidencePassage.claim_id.in_(claim_ids))
        )
        await db.execute(
            delete(VerdictAuditLog).where(VerdictAuditLog.claim_id.in_(claim_ids))
        )
        # Delete claims
        await db.execute(
            delete(Claim).where(Claim.session_id == session_id)
        )

    # Delete transcript segments
    await db.execute(
        delete(TranscriptSegment).where(TranscriptSegment.session_id == session_id)
    )

    await db.delete(session)
    await db.commit()
    return {"status": "deleted", "session_id": session_id}
