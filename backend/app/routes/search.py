from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.claim import Claim
from app.models.session import Session

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query("", min_length=1),
    speaker: str | None = Query(None),
    verdict: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # Search claims
    claim_query = select(Claim)

    if q:
        claim_query = claim_query.where(
            or_(
                Claim.claim_text.ilike(f"%{q}%"),
                Claim.speaker_label.ilike(f"%{q}%"),
            )
        )

    if speaker:
        claim_query = claim_query.where(Claim.speaker_label.ilike(f"%{speaker}%"))

    if verdict:
        claim_query = claim_query.where(Claim.verdict_label == verdict)

    # Count total
    count_query = select(func.count()).select_from(claim_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    claim_query = (
        claim_query.order_by(Claim.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(claim_query)
    claims = result.scalars().all()

    # Also search sessions by title
    session_query = (
        select(Session).where(Session.title.ilike(f"%{q}%")).limit(5)
        if q
        else select(Session).limit(0)
    )
    session_result = await db.execute(session_query)
    sessions = session_result.scalars().all()

    return {
        "claims": [
            {
                "claim_id": c.id,
                "claim_text": c.claim_text,
                "speaker": c.speaker_label,
                "verdict_label": c.verdict_label,
                "confidence": c.verdict_confidence,
                "session_id": c.session_id,
                "start_ms": c.start_ms,
            }
            for c in claims
        ],
        "sessions": [
            {
                "session_id": s.id,
                "title": s.title,
                "status": s.status,
                "claims_count": 0,  # simplified
            }
            for s in sessions
        ],
        "total_claims": total,
        "page": page,
        "per_page": per_page,
    }
