from __future__ import annotations

from datetime import UTC, datetime, date
from typing import Any
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from newsletter.db import Base
from newsletter.enums import (
    DocumentKind,
    ResearchJobStage,
    ResearchJobStatus,
    SourcePlatform,
    SourceStatus,
    TrustTier,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    canonical_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    youtube_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    x_handles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sources: Mapped[list[Source]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    jobs: Mapped[list[ResearchJob]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    dossiers: Mapped[list[Dossier]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class ResearchJob(Base, TimestampMixin):
    __tablename__ = "research_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=ResearchJobStatus.queued.value, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default=ResearchJobStage.queued.value, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subject: Mapped[Subject] = relationship(back_populates="jobs")


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trust_tier: Mapped[str] = mapped_column(String(32), default=TrustTier.unknown.value, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=SourceStatus.discovered.value, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject: Mapped[Subject] = relationship(back_populates="sources")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="source", cascade="all, delete-orphan")
    documents: Mapped[list[Document]] = relationship(back_populates="source", cascade="all, delete-orphan")
    claims: Mapped[list[Claim]] = relationship(back_populates="source", cascade="all, delete-orphan")
    events: Mapped[list[Event]] = relationship(back_populates="source", cascade="all, delete-orphan")
    quotes: Mapped[list[Quote]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="artifacts")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), default=DocumentKind.other.value, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="claims")


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="events")


class Quote(Base, TimestampMixin):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="quotes")


class Dossier(Base, TimestampMixin):
    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sections: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    citation_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="dossiers")

