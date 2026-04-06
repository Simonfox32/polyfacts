from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_user
from app.db import get_db
from app.models.claim import Claim
from app.models.session import Session
from app.models.user import User, UserLike, UserSave, WatchHistory
from app.schemas.session import SessionResponse

router = APIRouter(prefix="/v1", tags=["user-features"])


class ToggleResponse(BaseModel):
    session_id: str
    active: bool


class LikeCountResponse(BaseModel):
    session_id: str
    count: int
    liked_by_me: bool


class WatchRequest(BaseModel):
    progress_seconds: float = Field(default=0, ge=0)


class WatchResponse(BaseModel):
    session_id: str
    progress_seconds: float
    last_watched_at: datetime


class WatchHistoryItem(BaseModel):
    session_id: str
    title: str | None
    status: str
    channel_name: str | None = None
    duration_seconds: int | None
    media_type: str = "audio"
    claims_count: int
    verdict_distribution: dict[str, int] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    created_at: datetime
    last_watched_at: datetime
    progress_seconds: float


async def _get_session_or_404(session_id: str, db: AsyncSession) -> Session:
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _build_session_summaries(
    db: AsyncSession, sessions: list[Session]
) -> dict[str, SessionResponse]:
    session_ids = [session.id for session in sessions]
    verdicts_by_session = {session.id: {} for session in sessions}
    claim_counts = {session.id: 0 for session in sessions}

    if session_ids:
        claim_rows = await db.execute(
            select(Claim.session_id, Claim.verdict_label).where(Claim.session_id.in_(session_ids))
        )
        for session_id, verdict_label in claim_rows.all():
            claim_counts[session_id] += 1
            label = verdict_label or "UNVERIFIED"
            verdict_distribution = verdicts_by_session[session_id]
            verdict_distribution[label] = verdict_distribution.get(label, 0) + 1

    return {
        session.id: SessionResponse(
            session_id=session.id,
            title=session.title,
            status=session.status,
            channel_name=session.channel_name,
            duration_seconds=session.duration_seconds,
            media_type=getattr(session, "media_type", "audio"),
            claims_count=claim_counts[session.id],
            verdict_distribution=verdicts_by_session[session.id],
            thumbnail_url=f"/v1/media/{session.id}/thumbnail" if session.thumbnail_path else None,
            created_at=session.created_at,
        )
        for session in sessions
    }


@router.post("/sessions/{session_id}/like", response_model=ToggleResponse)
async def like_session(
    session_id: str,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)
    existing = await db.execute(
        select(UserLike).where(
            UserLike.user_id == current_user.id, UserLike.session_id == session_id
        )
    )
    like = existing.scalar_one_or_none()
    if like is None:
        db.add(UserLike(user_id=current_user.id, session_id=session_id))
        await db.commit()

    return ToggleResponse(session_id=session_id, active=True)


@router.delete("/sessions/{session_id}/like", response_model=ToggleResponse)
async def unlike_session(
    session_id: str,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)
    await db.execute(
        delete(UserLike).where(
            UserLike.user_id == current_user.id, UserLike.session_id == session_id
        )
    )
    await db.commit()
    return ToggleResponse(session_id=session_id, active=False)


@router.get("/sessions/{session_id}/like-count", response_model=LikeCountResponse)
async def like_count(
    session_id: str,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)

    count_result = await db.execute(
        select(func.count(UserLike.id)).where(UserLike.session_id == session_id)
    )
    count = count_result.scalar_one()

    liked_by_me = False
    if current_user is not None:
        like_result = await db.execute(
            select(UserLike.id).where(
                UserLike.user_id == current_user.id, UserLike.session_id == session_id
            )
        )
        liked_by_me = like_result.scalar_one_or_none() is not None

    return LikeCountResponse(session_id=session_id, count=count, liked_by_me=liked_by_me)


@router.post("/sessions/{session_id}/save", response_model=ToggleResponse)
async def save_session(
    session_id: str,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)
    existing = await db.execute(
        select(UserSave).where(
            UserSave.user_id == current_user.id, UserSave.session_id == session_id
        )
    )
    save = existing.scalar_one_or_none()
    if save is None:
        db.add(UserSave(user_id=current_user.id, session_id=session_id))
        await db.commit()

    return ToggleResponse(session_id=session_id, active=True)


@router.delete("/sessions/{session_id}/save", response_model=ToggleResponse)
async def unsave_session(
    session_id: str,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)
    await db.execute(
        delete(UserSave).where(
            UserSave.user_id == current_user.id, UserSave.session_id == session_id
        )
    )
    await db.commit()
    return ToggleResponse(session_id=session_id, active=False)


@router.post("/sessions/{session_id}/watch", response_model=WatchResponse)
async def watch_session(
    session_id: str,
    payload: WatchRequest,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_session_or_404(session_id, db)
    now = datetime.now(timezone.utc)

    existing = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == current_user.id, WatchHistory.session_id == session_id
        )
    )
    watch_history = existing.scalar_one_or_none()
    if watch_history is None:
        watch_history = WatchHistory(
            user_id=current_user.id,
            session_id=session_id,
            progress_seconds=payload.progress_seconds,
            last_watched_at=now,
        )
        db.add(watch_history)
    else:
        watch_history.progress_seconds = payload.progress_seconds
        watch_history.last_watched_at = now

    await db.commit()
    await db.refresh(watch_history)

    return WatchResponse(
        session_id=session_id,
        progress_seconds=watch_history.progress_seconds,
        last_watched_at=watch_history.last_watched_at,
    )


@router.get("/sessions/{session_id}/watch")
async def get_watch_progress(
    session_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's watch progress for a session."""
    result = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.session_id == session_id,
        )
    )
    watch = result.scalar_one_or_none()
    if not watch:
        return {"progress_seconds": 0}
    return {"progress_seconds": watch.progress_seconds}


@router.get("/me/liked", response_model=list[SessionResponse])
async def my_liked_sessions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .join(UserLike, UserLike.session_id == Session.id)
        .where(UserLike.user_id == current_user.id)
        .order_by(UserLike.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    sessions = result.scalars().all()
    summaries = await _build_session_summaries(db, sessions)
    return [summaries[session.id] for session in sessions]


@router.get("/me/saved", response_model=list[SessionResponse])
async def my_saved_sessions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .join(UserSave, UserSave.session_id == Session.id)
        .where(UserSave.user_id == current_user.id)
        .order_by(UserSave.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    sessions = result.scalars().all()
    summaries = await _build_session_summaries(db, sessions)
    return [summaries[session.id] for session in sessions]


@router.get("/me/history", response_model=list[WatchHistoryItem])
async def my_watch_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WatchHistory, Session)
        .join(Session, WatchHistory.session_id == Session.id)
        .where(WatchHistory.user_id == current_user.id)
        .order_by(WatchHistory.last_watched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = result.all()
    sessions = [session for _, session in rows]
    summaries = await _build_session_summaries(db, sessions)

    return [
        WatchHistoryItem(
            **summaries[session.id].model_dump(),
            last_watched_at=watch_history.last_watched_at,
            progress_seconds=watch_history.progress_seconds,
        )
        for watch_history, session in rows
    ]
