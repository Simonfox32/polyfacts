"""Comment and comment vote models."""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_prefixed_id


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: generate_prefixed_id("cmt")
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    dislike_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    replies: Mapped[list["Comment"]] = relationship(
        "Comment",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="Comment.created_at.asc()",
    )
    parent: Mapped["Comment | None"] = relationship(
        "Comment",
        back_populates="replies",
        remote_side="Comment.id",
    )
    votes: Mapped[list["CommentVote"]] = relationship(
        back_populates="comment", cascade="all, delete-orphan"
    )


class CommentVote(TimestampMixin, Base):
    __tablename__ = "comment_votes"
    __table_args__ = (UniqueConstraint("user_id", "comment_id", name="uq_user_comment_vote"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: generate_prefixed_id("cv")
    )
    comment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vote_type: Mapped[str] = mapped_column(String(10), nullable=False)

    comment: Mapped["Comment"] = relationship(back_populates="votes")
