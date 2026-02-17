from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_prefixed_id


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "sess")
    )
    title: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    channel_name: Mapped[str | None] = mapped_column(String(200))
    broadcast_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_file_path: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # status: queued | processing | completed | failed
    processing_stage: Mapped[str | None] = mapped_column(String(50))
    # stage: asr | claim_detection | evidence_retrieval | verdict_generation
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="TranscriptSegment.start_ms"
    )
    claims: Mapped[list] = relationship(
        "Claim", back_populates="session", cascade="all, delete-orphan"
    )


class TranscriptSegment(TimestampMixin, Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "seg")
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    speaker_label: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_final: Mapped[bool] = mapped_column(default=True)

    # Relationships
    session: Mapped["Session"] = relationship(back_populates="transcript_segments")
