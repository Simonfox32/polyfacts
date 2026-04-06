from datetime import datetime

from pydantic import BaseModel


class SpeakerInfo(BaseModel):
    label: str
    party: str | None = None


class ClipUploadResponse(BaseModel):
    clip_id: str
    status: str
    estimated_processing_seconds: int | None = None
    status_url: str


class ClipStatusResponse(BaseModel):
    clip_id: str
    status: str
    stage: str | None = None
    progress_pct: int = 0
    claims_detected: int = 0
    claims_verdicted: int = 0
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TranscriptSegmentResponse(BaseModel):
    segment_id: str
    speaker_label: str | None
    text: str
    start_ms: int
    end_ms: int


class SessionResponse(BaseModel):
    session_id: str
    title: str | None
    status: str
    channel_name: str | None = None
    duration_seconds: int | None
    media_type: str = "audio"
    view_count: int = 0
    claims_count: int
    verdict_distribution: dict[str, int] = {}
    thumbnail_url: str | None = None
    created_at: datetime


class SessionDetailResponse(BaseModel):
    session_id: str
    title: str | None
    description: str | None = None
    status: str
    channel_name: str | None = None
    broadcast_date: datetime | None = None
    duration_seconds: int | None
    media_type: str = "audio"
    view_count: int = 0
    claims_count: int
    speakers: list[str] = []
    verdict_distribution: dict[str, int] = {}
    created_at: datetime
    completed_at: datetime | None = None
