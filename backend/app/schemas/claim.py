from datetime import datetime

from pydantic import BaseModel


class NormalizedClaim(BaseModel):
    subject: str
    predicate: str
    object: str
    qualifiers: list[str] = []


class TimeScope(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    ambiguity_notes: str | None = None


class Speaker(BaseModel):
    speaker_label: str
    party: str | None = None
    role: str | None = None


class TimestampRange(BaseModel):
    start_ms: int
    end_ms: int


class SourceResponse(BaseModel):
    source_id: str
    url: str
    title: str
    publisher: str
    publication_date: str | None = None
    source_tier: str
    snippet_supporting: str
    relevance_to_claim: str
    last_verified_at: datetime | None = None
    archived_snapshot_url: str | None = None


class VerdictResponse(BaseModel):
    label: str
    confidence: float | None
    rationale_summary: str | None
    rationale_bullets: list[str] = []
    version: int = 1
    generated_at: datetime | None = None
    model_used: str | None = None


class ClaimSummaryResponse(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    speaker: Speaker | None = None
    timestamp_range: TimestampRange
    verdict: VerdictResponse | None = None
    source_count: int = 0


class ClaimDetailResponse(BaseModel):
    claim_id: str
    session_id: str
    claim_text: str
    normalized_claim: NormalizedClaim | None = None
    time_scope: TimeScope | None = None
    location_scope: str | None = None
    speaker: Speaker | None = None
    timestamp_range: TimestampRange
    claim_type: str
    claim_worthiness_score: float
    required_evidence_types: list[str] = []
    verdict: VerdictResponse | None = None
    sources: list[SourceResponse] = []
    what_would_change_verdict: str | None = None


class ClaimSearchResponse(BaseModel):
    results: list[ClaimSummaryResponse]
    total: int
    page: int
    per_page: int
