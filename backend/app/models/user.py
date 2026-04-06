from datetime import datetime
from functools import partial
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_prefixed_id


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=partial(generate_prefixed_id, "usr")
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    likes: Mapped[list["UserLike"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    saves: Mapped[list["UserSave"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    watch_history: Mapped[list["WatchHistory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserLike(TimestampMixin, Base):
    __tablename__ = "user_likes"
    __table_args__ = (UniqueConstraint("user_id", "session_id", name="uq_user_likes_user_session"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=partial(generate_prefixed_id, "ulk")
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped["User"] = relationship(back_populates="likes")
    session: Mapped["Session"] = relationship()


class UserSave(TimestampMixin, Base):
    __tablename__ = "user_saves"
    __table_args__ = (UniqueConstraint("user_id", "session_id", name="uq_user_saves_user_session"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=partial(generate_prefixed_id, "usv")
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped["User"] = relationship(back_populates="saves")
    session: Mapped["Session"] = relationship()


class WatchHistory(TimestampMixin, Base):
    __tablename__ = "watch_history"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_watch_history_user_session"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=partial(generate_prefixed_id, "wh")
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    progress_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="watch_history")
    session: Mapped["Session"] = relationship()


class ClaimReaction(TimestampMixin, Base):
    __tablename__ = "claim_reactions"
    __table_args__ = (UniqueConstraint("user_id", "claim_id", name="uq_user_claim_reaction"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"cr_{uuid4().hex[:12]}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reaction: Mapped[str] = mapped_column(String(10), nullable=False)
