from datetime import datetime
from functools import partial

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_prefixed_id


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "clm")
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)

    # Verbatim text as spoken
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Normalized claim structure: {subject, predicate, object, qualifiers}
    normalized_claim: Mapped[dict | None] = mapped_column(JSONB)

    # Scoping
    time_scope: Mapped[dict | None] = mapped_column(JSONB)
    # {start_date, end_date, is_current, ambiguity_notes}
    location_scope: Mapped[str | None] = mapped_column(String(200))

    # Speaker info
    speaker_label: Mapped[str | None] = mapped_column(String(200))
    speaker_party: Mapped[str | None] = mapped_column(String(100))
    speaker_role: Mapped[str | None] = mapped_column(String(200))

    # Timestamps in the audio
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Classification
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # checkable_fact | opinion | forecast | definition | value_judgment
    claim_worthiness_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Evidence requirements
    required_evidence_types: Mapped[list | None] = mapped_column(JSONB)

    # Verdict
    verdict_label: Mapped[str | None] = mapped_column(String(20))
    # TRUE | MOSTLY_TRUE | HALF_TRUE | MOSTLY_FALSE | FALSE | UNVERIFIED
    verdict_confidence: Mapped[float | None] = mapped_column(Float)
    verdict_rationale_summary: Mapped[str | None] = mapped_column(String(500))
    verdict_rationale_bullets: Mapped[list | None] = mapped_column(JSONB)
    verdict_version: Mapped[int] = mapped_column(Integer, default=1)
    verdict_model_used: Mapped[str | None] = mapped_column(String(100))
    verdict_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Transparency
    what_would_change_verdict: Mapped[str | None] = mapped_column(Text)

    # Relationships
    session: Mapped["Session"] = relationship(back_populates="claims")  # noqa: F821
    evidence_passages: Mapped[list["EvidencePassage"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["VerdictAuditLog"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "src")
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    publisher: Mapped[str] = mapped_column(String(500), nullable=False)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    # tier_1_government_primary | tier_2_court_academic | tier_3_major_outlet
    # tier_4_regional_specialty | tier_5_other
    content_text: Mapped[str | None] = mapped_column(Text)
    content_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    archived_snapshot_url: Mapped[str | None] = mapped_column(String(2000))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(30), default="active")
    # active | link_rot_detected | archived_only

    # Relationships
    evidence_passages: Mapped[list["EvidencePassage"]] = relationship(back_populates="source")


class EvidencePassage(TimestampMixin, Base):
    __tablename__ = "evidence_passages"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "evd")
    )
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)

    snippet: Mapped[str] = mapped_column(String(2000), nullable=False)
    relevance_to_claim: Mapped[str] = mapped_column(String(30), nullable=False)
    # supports | contradicts | provides_context | partially_supports
    relevance_score: Mapped[float | None] = mapped_column(Float)
    retrieval_method: Mapped[str | None] = mapped_column(String(50))
    # bm25 | embedding | api | rrf_fusion

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="evidence_passages")
    source: Mapped["Source"] = relationship(back_populates="evidence_passages")


class VerdictAuditLog(Base):
    __tablename__ = "verdict_audit_log"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=partial(generate_prefixed_id, "aud")
    )
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict_label: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale_summary: Mapped[str | None] = mapped_column(String(500))
    rationale_bullets: Mapped[list | None] = mapped_column(JSONB)
    model_used: Mapped[str | None] = mapped_column(String(100))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_ids: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="audit_logs")
