from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.adapters.base import AdapterUnavailable
from newsletter.adapters.exa_discovery import discover_via_exa
from newsletter.adapters.web import WebAdapter
from newsletter.adapters.x_adapter import XAdapter
from newsletter.adapters.youtube import YouTubeAdapter
from newsletter.db import get_session_factory
from newsletter.enums import ResearchJobStage, ResearchJobStatus, SourceStatus
from newsletter.models import Artifact, Chunk, Claim, Document, Event, Quote, ResearchJob, Source, Subject
from newsletter.services.dossier import build_dossier
from newsletter.services.extraction import (
    extract_claim_payloads,
    extract_event_payloads,
    extract_quote_payloads,
)
from newsletter.services.ingestion import ingest_document
from newsletter.storage.object_store import FilesystemObjectStore


class ResearchService:
    def __init__(self) -> None:
        self.session_factory = get_session_factory
        self.object_store = FilesystemObjectStore()
        self.adapter_registry = {
            "web": WebAdapter(),
            "youtube": YouTubeAdapter(),
            "x": XAdapter(),
        }

    def run_job(self, job_id: str) -> None:
        session = self.session_factory()()
        try:
            job = session.get(ResearchJob, job_id)
            if job is None:
                return
            subject = session.get(Subject, job.subject_id)
            if subject is None:
                job.status = ResearchJobStatus.failed.value
                job.stage = ResearchJobStage.failed.value
                job.error_message = "Subject not found."
                session.commit()
                return

            job.status = ResearchJobStatus.running.value
            job.stage = ResearchJobStage.discover.value
            job.started_at = datetime.now(UTC)
            session.commit()

            stats = {"sources_discovered": 0, "sources_processed": 0, "sources_failed": 0}

            self._discover_sources(session, subject, stats)
            self._fetch_sources(session, subject, job, stats)
            self._normalize_sources(session, subject, job)
            self._ingest_documents(session, subject, job)
            self._extract_documents(session, subject, job)

            job.stage = ResearchJobStage.resolve.value
            job.stats = stats
            session.commit()

            job.stage = ResearchJobStage.assemble.value
            build_dossier(session, subject)
            session.commit()

            stats["sources_processed"] = session.query(Source).filter_by(
                subject_id=subject.id, status=SourceStatus.processed.value
            ).count()
            stats["sources_failed"] = session.query(Source).filter_by(
                subject_id=subject.id, status=SourceStatus.failed.value
            ).count()
            job.stats = stats
            job.stage = ResearchJobStage.completed.value
            job.status = ResearchJobStatus.completed.value
            job.completed_at = datetime.now(UTC)
            session.commit()
        except Exception as exc:
            session.rollback()
            job = session.get(ResearchJob, job_id)
            if job is not None:
                job.status = ResearchJobStatus.failed.value
                job.stage = ResearchJobStage.failed.value
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                session.commit()
            raise
        finally:
            session.close()

    def _discover_sources(self, session: Session, subject: Subject, stats: dict[str, int]) -> None:
        known_urls = {
            (source.platform, source.url)
            for source in session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
        }

        # seeded adapter discovery (youtube_urls + canonical_urls + x_handles)
        all_discovered = []
        for adapter in self.adapter_registry.values():
            all_discovered.extend(adapter.discover(subject))

        # autonomous discovery via Exa neural search
        all_discovered.extend(discover_via_exa(subject))

        for discovered in all_discovered:
            source_key = (discovered.platform, discovered.url)
            if source_key in known_urls:
                continue
            session.add(
                Source(
                    subject_id=subject.id,
                    platform=discovered.platform,
                    source_type=discovered.source_type,
                    url=discovered.url,
                    trust_tier=discovered.trust_tier,
                    title=discovered.title,
                    author=discovered.author,
                    metadata_json=discovered.metadata_json,
                )
            )
            known_urls.add(source_key)
            stats["sources_discovered"] += 1
        session.commit()

    def _fetch_sources(self, session: Session, subject: Subject, job: ResearchJob, stats: dict[str, int]) -> None:
        job.stage = ResearchJobStage.fetch.value
        session.commit()
        sources = session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
        for source in sources:
            if source.status != SourceStatus.discovered.value:
                continue
            adapter = self.adapter_registry[source.platform]
            try:
                artifact = adapter.fetch_source(source)
                object_key = self._build_object_key(subject.id, source.id, artifact.artifact_type, artifact.media_type)
                stored = self.object_store.put_bytes(object_key, artifact.payload)
                session.add(
                    Artifact(
                        source_id=source.id,
                        artifact_type=artifact.artifact_type,
                        object_key=stored.object_key,
                        media_type=artifact.media_type,
                        byte_size=stored.byte_size,
                        checksum=stored.checksum,
                        metadata_json=artifact.metadata_json,
                    )
                )
                source.status = SourceStatus.fetched.value
                source.fetched_at = datetime.now(UTC)
                source.last_error = None
            except AdapterUnavailable as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
            except Exception as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
            session.commit()

    def _normalize_sources(self, session: Session, subject: Subject, job: ResearchJob) -> None:
        job.stage = ResearchJobStage.normalize.value
        session.commit()
        sources = session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
        for source in sources:
            if source.status != SourceStatus.fetched.value:
                continue
            adapter = self.adapter_registry[source.platform]
            artifact = source.artifacts[-1] if source.artifacts else None
            if artifact is None:
                source.status = SourceStatus.failed.value
                source.last_error = "No artifact stored for fetched source."
                session.commit()
                continue

            data = (self.object_store.root / artifact.object_key).read_bytes()
            try:
                normalized = adapter.normalize(
                    source,
                    type("ArtifactProxy", (), {
                        "artifact_type": artifact.artifact_type,
                        "media_type": artifact.media_type,
                        "payload": data,
                        "metadata_json": artifact.metadata_json,
                    })(),
                )
                document = Document(
                    source_id=source.id,
                    kind=normalized.kind,
                    title=normalized.title,
                    content_markdown=normalized.content_markdown,
                    content_text=normalized.content_text,
                    metadata_json=normalized.metadata_json,
                )
                session.add(document)
                session.flush()
                source.title = normalized.title
                source.status = SourceStatus.normalized.value
                source.last_error = None
            except AdapterUnavailable as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
            except Exception as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
            session.commit()

    def _ingest_documents(self, session: Session, subject: Subject, job: ResearchJob) -> None:
        """Chunk all normalized documents and upsert vectors into Qdrant."""
        job.stage = ResearchJobStage.extract.value  # reuse stage slot; ingest runs before extract
        session.commit()
        sources = session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
        for source in sources:
            if source.status != SourceStatus.normalized.value:
                continue
            for document in source.documents:
                try:
                    ingest_document(document.id, session)
                except Exception:
                    logger.exception("Vector ingestion failed for document %s", document.id)

    def _extract_documents(self, session: Session, subject: Subject, job: ResearchJob) -> None:
        job.stage = ResearchJobStage.extract.value
        session.commit()
        sources = session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
        for source in sources:
            if source.status != SourceStatus.normalized.value:
                continue
            for document in source.documents:
                self._persist_claims(session, subject, source, document)
                self._persist_events(session, subject, source, document)
                self._persist_quotes(session, subject, source, document)
            source.status = SourceStatus.processed.value
            session.commit()

    def _persist_claims(self, session: Session, subject: Subject, source: Source, document: Document) -> None:
        for payload in extract_claim_payloads(subject, source, document):
            session.add(
                Claim(
                    subject_id=subject.id,
                    source_id=source.id,
                    claim_type=str(payload["claim_type"]),
                    statement=str(payload["statement"]),
                    confidence=float(payload["confidence"]),
                    citations=list(payload["citations"]),
                    rationale=str(payload["rationale"]),
                )
            )
        session.commit()

    def _persist_events(self, session: Session, subject: Subject, source: Source, document: Document) -> None:
        for payload in extract_event_payloads(source, document):
            session.add(
                Event(
                    subject_id=subject.id,
                    source_id=source.id,
                    event_type=str(payload["event_type"]),
                    summary=str(payload["summary"]),
                    event_date=payload["event_date"],
                    confidence=float(payload["confidence"]),
                    citations=list(payload["citations"]),
                )
            )
        session.commit()

    def _persist_quotes(self, session: Session, subject: Subject, source: Source, document: Document) -> None:
        for payload in extract_quote_payloads(source, document, default_speaker=subject.name):
            session.add(
                Quote(
                    subject_id=subject.id,
                    source_id=source.id,
                    speaker=payload["speaker"],
                    quote_text=str(payload["quote_text"]),
                    confidence=float(payload["confidence"]),
                    citations=list(payload["citations"]),
                )
            )
        session.commit()

    @staticmethod
    def _build_object_key(subject_id: str, source_id: str, artifact_type: str, media_type: str) -> str:
        extension = {
            "text/html": "html",
            "application/json": "json",
            "text/plain": "txt",
        }.get(media_type, "bin")
        return str(Path(subject_id) / source_id / f"{artifact_type}.{extension}")

