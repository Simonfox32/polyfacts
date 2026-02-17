from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.claim import Claim, EvidencePassage, Source
from app.schemas.claim import (
    ClaimDetailResponse,
    ClaimSearchResponse,
    ClaimSummaryResponse,
    NormalizedClaim,
    SourceResponse,
    Speaker,
    TimeScope,
    TimestampRange,
    VerdictResponse,
)

router = APIRouter(prefix="/v1", tags=["claims"])


def _build_verdict(claim: Claim) -> VerdictResponse | None:
    if not claim.verdict_label:
        return None
    return VerdictResponse(
        label=claim.verdict_label,
        confidence=claim.verdict_confidence,
        rationale_summary=claim.verdict_rationale_summary,
        rationale_bullets=claim.verdict_rationale_bullets or [],
        version=claim.verdict_version,
        generated_at=claim.verdict_generated_at,
        model_used=claim.verdict_model_used,
    )


def _build_speaker(claim: Claim) -> Speaker | None:
    if not claim.speaker_label:
        return None
    return Speaker(
        speaker_label=claim.speaker_label,
        party=claim.speaker_party,
        role=claim.speaker_role,
    )


def _build_source_response(passage: EvidencePassage) -> SourceResponse:
    source = passage.source
    return SourceResponse(
        source_id=source.id,
        url=source.url,
        title=source.title,
        publisher=source.publisher,
        publication_date=str(source.publication_date.date()) if source.publication_date else None,
        source_tier=source.source_tier,
        snippet_supporting=passage.snippet,
        relevance_to_claim=passage.relevance_to_claim,
        last_verified_at=source.last_verified_at,
        archived_snapshot_url=source.archived_snapshot_url,
    )


@router.get("/sessions/{session_id}/claims", response_model=ClaimSearchResponse)
async def list_session_claims(
    session_id: str,
    verdict: str | None = Query(None, description="Comma-separated verdict labels to filter"),
    speaker: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Claim).where(Claim.session_id == session_id)

    if verdict:
        labels = [v.strip() for v in verdict.split(",")]
        query = query.where(Claim.verdict_label.in_(labels))
    if speaker:
        query = query.where(Claim.speaker_label.ilike(f"%{speaker}%"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Claim.start_ms).offset((page - 1) * per_page).limit(per_page)
    query = query.options(selectinload(Claim.evidence_passages))
    result = await db.execute(query)
    claims = result.scalars().all()

    return ClaimSearchResponse(
        results=[
            ClaimSummaryResponse(
                claim_id=c.id,
                claim_text=c.claim_text,
                claim_type=c.claim_type,
                speaker=_build_speaker(c),
                timestamp_range=TimestampRange(start_ms=c.start_ms, end_ms=c.end_ms),
                verdict=_build_verdict(c),
                source_count=len(c.evidence_passages),
            )
            for c in claims
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/claims/{claim_id}", response_model=ClaimDetailResponse)
async def get_claim_detail(claim_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Claim)
        .where(Claim.id == claim_id)
        .options(
            selectinload(Claim.evidence_passages).selectinload(EvidencePassage.source)
        )
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    normalized = None
    if claim.normalized_claim:
        normalized = NormalizedClaim(**claim.normalized_claim)

    time_scope = None
    if claim.time_scope:
        time_scope = TimeScope(**claim.time_scope)

    return ClaimDetailResponse(
        claim_id=claim.id,
        session_id=claim.session_id,
        claim_text=claim.claim_text,
        normalized_claim=normalized,
        time_scope=time_scope,
        location_scope=claim.location_scope,
        speaker=_build_speaker(claim),
        timestamp_range=TimestampRange(start_ms=claim.start_ms, end_ms=claim.end_ms),
        claim_type=claim.claim_type,
        claim_worthiness_score=claim.claim_worthiness_score,
        required_evidence_types=claim.required_evidence_types or [],
        verdict=_build_verdict(claim),
        sources=[_build_source_response(p) for p in claim.evidence_passages],
        what_would_change_verdict=claim.what_would_change_verdict,
    )
