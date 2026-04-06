"""Comment routes for session discussions."""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_user
from app.db import get_db
from app.models.comment import Comment, CommentVote
from app.models.user import User

router = APIRouter(prefix="/v1", tags=["comments"])


class CreateCommentRequest(BaseModel):
    text: str
    parent_id: str | None = None


class VoteRequest(BaseModel):
    vote_type: str  # "like" or "dislike"


def _serialize_comment(
    comment: Comment,
    children_by_parent: dict[str, list[Comment]],
    user_map: dict[str, str],
    user_votes: dict[str, str],
) -> dict:
    child_comments = children_by_parent.get(comment.id, [])
    replies = []
    for reply in child_comments:
        serialized_reply = _serialize_comment(reply, children_by_parent, user_map, user_votes)
        if not reply.is_deleted or serialized_reply["replies"]:
            replies.append(serialized_reply)

    return {
        "comment_id": comment.id,
        "user_id": comment.user_id,
        "username": user_map.get(comment.user_id, "Unknown"),
        "text": "[deleted]" if comment.is_deleted else comment.text,
        "like_count": comment.like_count,
        "dislike_count": comment.dislike_count,
        "is_deleted": comment.is_deleted,
        "user_vote": user_votes.get(comment.id),
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "replies": replies,
    }


@router.get("/sessions/{session_id}/comments")
async def list_comments(
    session_id: str,
    sort: str = Query("newest", pattern="^(newest|top)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List top-level comments with nested replies."""
    order = Comment.created_at.desc() if sort == "newest" else Comment.like_count.desc()

    total_result = await db.execute(
        select(func.count()).where(Comment.session_id == session_id, Comment.parent_id.is_(None))
    )
    total = total_result.scalar_one()

    top_level_result = await db.execute(
        select(Comment.id)
        .where(Comment.session_id == session_id, Comment.parent_id.is_(None))
        .order_by(order)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    top_level_ids = list(top_level_result.scalars())

    if not top_level_ids:
        return {"comments": [], "total": total, "page": page, "per_page": per_page}

    comments_result = await db.execute(
        select(Comment)
        .where(Comment.session_id == session_id)
        .order_by(Comment.created_at.asc())
    )
    all_comments = comments_result.scalars().all()
    comments_by_id = {comment.id: comment for comment in all_comments}

    children_by_parent: dict[str, list[Comment]] = defaultdict(list)
    for comment in all_comments:
        if comment.parent_id:
            children_by_parent[comment.parent_id].append(comment)

    all_user_ids = {comment.user_id for comment in all_comments}
    user_map: dict[str, str] = {}
    if all_user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(all_user_ids)))
        user_map = {db_user.id: db_user.username for db_user in users_result.scalars()}

    visible_comment_ids = set()

    def collect_ids(comment: Comment) -> None:
        visible_comment_ids.add(comment.id)
        for child in children_by_parent.get(comment.id, []):
            collect_ids(child)

    top_level_comments = [
        comments_by_id[comment_id]
        for comment_id in top_level_ids
        if comment_id in comments_by_id
    ]
    for comment in top_level_comments:
        collect_ids(comment)

    user_votes: dict[str, str] = {}
    if user and visible_comment_ids:
        votes_result = await db.execute(
            select(CommentVote).where(
                CommentVote.user_id == user.id,
                CommentVote.comment_id.in_(visible_comment_ids),
            )
        )
        user_votes = {vote.comment_id: vote.vote_type for vote in votes_result.scalars()}

    return {
        "comments": [
            _serialize_comment(comment, children_by_parent, user_map, user_votes)
            for comment in top_level_comments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/sessions/{session_id}/comments", status_code=201)
async def create_comment(
    session_id: str,
    body: CreateCommentRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new comment or reply."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment text cannot be empty")

    if body.parent_id:
        parent = await db.get(Comment, body.parent_id)
        if not parent or parent.session_id != session_id:
            raise HTTPException(status_code=404, detail="Parent comment not found")

    comment = Comment(
        session_id=session_id,
        user_id=user.id,
        parent_id=body.parent_id,
        text=text,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return {
        "comment_id": comment.id,
        "user_id": comment.user_id,
        "username": user.username,
        "text": comment.text,
        "like_count": 0,
        "dislike_count": 0,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.post("/comments/{comment_id}/vote")
async def vote_comment(
    comment_id: str,
    body: VoteRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Like or dislike a comment. Toggles if same vote exists."""
    if body.vote_type not in ("like", "dislike"):
        raise HTTPException(
            status_code=400,
            detail="vote_type must be 'like' or 'dislike'",
        )

    comment = await db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    existing_result = await db.execute(
        select(CommentVote).where(
            CommentVote.user_id == user.id,
            CommentVote.comment_id == comment_id,
        )
    )
    existing_vote = existing_result.scalar_one_or_none()

    if existing_vote:
        if existing_vote.vote_type == body.vote_type:
            if body.vote_type == "like":
                comment.like_count = max(0, comment.like_count - 1)
            else:
                comment.dislike_count = max(0, comment.dislike_count - 1)
            await db.delete(existing_vote)
            await db.commit()
            return {
                "status": "removed",
                "like_count": comment.like_count,
                "dislike_count": comment.dislike_count,
            }

        if existing_vote.vote_type == "like":
            comment.like_count = max(0, comment.like_count - 1)
            comment.dislike_count += 1
        else:
            comment.dislike_count = max(0, comment.dislike_count - 1)
            comment.like_count += 1
        existing_vote.vote_type = body.vote_type
        await db.commit()
        return {
            "status": "switched",
            "like_count": comment.like_count,
            "dislike_count": comment.dislike_count,
        }

    vote = CommentVote(comment_id=comment_id, user_id=user.id, vote_type=body.vote_type)
    if body.vote_type == "like":
        comment.like_count += 1
    else:
        comment.dislike_count += 1
    db.add(vote)
    await db.commit()
    return {
        "status": "voted",
        "like_count": comment.like_count,
        "dislike_count": comment.dislike_count,
    }


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a comment (author or admin)."""
    comment = await db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this comment")

    comment.is_deleted = True
    comment.text = ""
    await db.commit()
    return {"status": "deleted"}
