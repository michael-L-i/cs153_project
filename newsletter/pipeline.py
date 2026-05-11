"""
Founder research pipeline.

Input:  founder name + optional context string
Output: chunks embedded in Qdrant, provenance in SQLite/Postgres

Stages:
  1. Find or create subject
  2. Discover URLs via Exa neural search
  3. Fetch each source (Firecrawl for web, youtube-transcript-api for video)
  4. Normalize to clean text
  5. Chunk → embed → upsert to Qdrant
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.adapters.base import AdapterUnavailable
from newsletter.adapters.exa_discovery import discover_via_exa
from newsletter.adapters.web import WebAdapter
from newsletter.adapters.youtube import YouTubeAdapter
from newsletter.db import create_db_and_tables, get_session_factory
from newsletter.enums import SourcePlatform, SourceStatus
from newsletter.models import Document, Source, Subject
from newsletter.services.ingestion import ingest_document

logger = logging.getLogger(__name__)

_web = WebAdapter()
_youtube = YouTubeAdapter()


def _adapter_for(platform: str):
    return _youtube if platform == SourcePlatform.youtube.value else _web


def run(name: str, context: str = "", *, verbose: bool = True) -> dict:
    """
    Run the full research pipeline for a founder.

    Args:
        name:    Founder's full name  e.g. "Peter Steinberger"
        context: Free-text context    e.g. "founder of OpenClaw"
        verbose: Print progress to stdout

    Returns:
        {"subject_id": str, "discovered": int, "processed": int,
         "failed": int, "chunks": int}
    """

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    create_db_and_tables()
    session: Session = get_session_factory()()

    try:
        # ── 1. Find or create subject ──────────────────────────────────────
        subject = session.scalars(select(Subject).where(Subject.name == name)).first()
        if subject is None:
            subject = Subject(name=name, notes=context or None)
            session.add(subject)
            session.commit()
            session.refresh(subject)
            log(f"\nCreated new subject: {name}")
        else:
            log(f"\nFound existing subject: {name}  (id: {subject.id[:8]}…)")

        # ── 2. Discover URLs via Exa ───────────────────────────────────────
        log(f"\n[1/4] Discovering sources for {name}…")

        existing_urls = {
            s.url
            for s in session.scalars(
                select(Source).where(Source.subject_id == subject.id)
            ).all()
        }

        discovered = discover_via_exa(subject)
        new_count = 0
        for d in discovered:
            if d.url in existing_urls:
                continue
            session.add(
                Source(
                    subject_id=subject.id,
                    platform=d.platform,
                    source_type=d.source_type,
                    url=d.url,
                    trust_tier=d.trust_tier,
                    title=d.title,
                    author=d.author,
                    metadata_json=d.metadata_json,
                )
            )
            existing_urls.add(d.url)
            new_count += 1

        session.commit()
        log(f"  → {len(discovered)} URLs found  ({new_count} new, {len(discovered) - new_count} already known)")

        # ── 3 – 5. Fetch → normalize → ingest all pending sources ─────────
        pending = session.scalars(
            select(Source).where(
                Source.subject_id == subject.id,
                Source.status.in_([SourceStatus.discovered.value, SourceStatus.normalized.value]),
            )
        ).all()

        log(f"\n[2/3] Processing {len(pending)} pending sources…\n")

        stats: dict = {"discovered": len(discovered), "processed": 0, "failed": 0, "chunks": 0}

        for source in pending:
            adapter = _adapter_for(source.platform)
            label = (source.title or source.url)[:72]

            try:
                # if already normalized, skip fetch+normalize and go straight to ingest
                if source.status == SourceStatus.normalized.value and source.documents:
                    doc = source.documents[-1]
                    chunk_count = ingest_document(doc.id, session)
                    source.status = SourceStatus.processed.value
                    session.commit()
                    stats["processed"] += 1
                    stats["chunks"] += chunk_count
                    log(f"  ✓  {label}  ({chunk_count} chunks)")
                    continue

                # fetch
                artifact = adapter.fetch_source(source)
                source.status = SourceStatus.fetched.value
                source.fetched_at = datetime.now(UTC)
                session.commit()

                # normalize
                normalized = adapter.normalize(source, artifact)
                doc = Document(
                    source_id=source.id,
                    kind=normalized.kind,
                    title=normalized.title,
                    content_markdown=normalized.content_markdown,
                    content_text=normalized.content_text,
                    metadata_json=normalized.metadata_json,
                )
                session.add(doc)
                source.title = normalized.title
                source.status = SourceStatus.normalized.value
                session.commit()
                session.refresh(doc)

                # chunk → embed → Qdrant
                chunk_count = ingest_document(doc.id, session)
                source.status = SourceStatus.processed.value
                session.commit()

                stats["processed"] += 1
                stats["chunks"] += chunk_count
                log(f"  ✓  {label}  ({chunk_count} chunks)")

            except AdapterUnavailable as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
                session.commit()
                stats["failed"] += 1
                log(f"  ✗  {label}")
                log(f"     {exc}")
            except Exception as exc:
                source.status = SourceStatus.failed.value
                source.last_error = str(exc)
                session.commit()
                stats["failed"] += 1
                log(f"  ✗  {label}")
                log(f"     {exc}")
                logger.exception("Unexpected error processing source %s", source.id)

        # ── Summary ───────────────────────────────────────────────────────
        log(f"\n[3/3] Done.\n")
        log(f"  Sources found      {stats['discovered']}")
        log(f"  Sources processed  {stats['processed']}")
        log(f"  Sources failed     {stats['failed']}")
        log(f"  Chunks in Qdrant   {stats['chunks']}")
        log(f"\n  subject_id: {subject.id}")
        log(f"\n  To search:")
        log(f"  curl 'http://localhost:8000/search?q=your+question&subject_id={subject.id}'")

        return {"subject_id": subject.id, **stats}

    finally:
        session.close()
