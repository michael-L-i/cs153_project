from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SubjectCreate(BaseModel):
    name: str
    company_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    canonical_urls: list[str] = Field(default_factory=list)
    youtube_urls: list[str] = Field(default_factory=list)
    x_handles: list[str] = Field(default_factory=list)
    notes: str | None = None


class SubjectRead(SubjectCreate):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchJobCreate(BaseModel):
    subject_id: str
    mode: str | None = None


class ResearchJobRead(BaseModel):
    id: str
    subject_id: str
    status: str
    stage: str
    error_message: str | None = None
    stats: dict[str, Any]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceRead(BaseModel):
    id: str
    platform: str
    source_type: str
    url: str
    title: str | None = None
    author: str | None = None
    trust_tier: str
    status: str
    fetched_at: datetime | None = None
    published_at: datetime | None = None
    metadata_json: dict[str, Any]
    last_error: str | None = None

    model_config = {"from_attributes": True}


class EventRead(BaseModel):
    id: str
    event_type: str
    summary: str
    event_date: date | None = None
    confidence: float
    citations: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class ClaimRead(BaseModel):
    id: str
    claim_type: str
    statement: str
    confidence: float
    citations: list[dict[str, Any]]
    rationale: str | None = None

    model_config = {"from_attributes": True}


class QuoteRead(BaseModel):
    id: str
    speaker: str | None = None
    quote_text: str
    confidence: float
    citations: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class DossierRead(BaseModel):
    id: str
    subject_id: str
    version: int
    summary: dict[str, Any]
    sections: dict[str, Any]
    citation_map: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WriterInputCreate(BaseModel):
    subject_id: str
    max_claims: int = 12
    max_quotes: int = 8
    max_events: int = 12


class WriterPacket(BaseModel):
    subject: dict[str, Any]
    dossier_version: int
    founder_profile: dict[str, Any]
    company_snapshot: dict[str, Any]
    timeline: list[dict[str, Any]]
    core_themes: list[str]
    notable_quotes: list[dict[str, Any]]
    supported_claims: list[dict[str, Any]]
    source_coverage: dict[str, Any]
    open_questions: list[str]

