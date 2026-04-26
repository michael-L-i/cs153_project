from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsletter.models import Claim, Dossier, Event, Quote, Source, Subject
from newsletter.services.extraction import derive_core_themes


def build_dossier(session: Session, subject: Subject) -> Dossier:
    source_rows = session.scalars(select(Source).where(Source.subject_id == subject.id)).all()
    claim_rows = session.scalars(select(Claim).where(Claim.subject_id == subject.id)).all()
    quote_rows = session.scalars(select(Quote).where(Quote.subject_id == subject.id)).all()
    event_rows = session.scalars(select(Event).where(Event.subject_id == subject.id).order_by(Event.event_date)).all()

    version = (
        session.scalar(select(func.max(Dossier.version)).where(Dossier.subject_id == subject.id))
        or 0
    ) + 1

    processed_sources = [source for source in source_rows if source.status == "processed"]
    failed_sources = [source for source in source_rows if source.status == "failed"]
    coverage = Counter(source.platform for source in source_rows)

    open_questions: list[str] = []
    if not quote_rows:
        open_questions.append("No high-confidence founder quotes were extracted yet.")
    if failed_sources:
        open_questions.append("Some sources failed to ingest and need follow-up or credentials.")
    if len(processed_sources) < 2:
        open_questions.append("Source coverage is still shallow; add more primary materials.")

    theme_list = derive_core_themes(claim_rows)

    citation_map = {
        source.id: {
            "url": source.url,
            "platform": source.platform,
            "title": source.title,
            "trust_tier": source.trust_tier,
        }
        for source in source_rows
    }

    dossier = Dossier(
        subject_id=subject.id,
        version=version,
        summary={
            "subject_name": subject.name,
            "company_name": subject.company_name,
            "source_count": len(source_rows),
            "processed_source_count": len(processed_sources),
            "claim_count": len(claim_rows),
            "event_count": len(event_rows),
            "quote_count": len(quote_rows),
        },
        sections={
            "founder_profile": {
                "name": subject.name,
                "aliases": subject.aliases,
                "notes": subject.notes,
            },
            "company_snapshot": {
                "company_name": subject.company_name,
                "canonical_urls": subject.canonical_urls,
                "x_handles": subject.x_handles,
                "youtube_urls": subject.youtube_urls,
            },
            "startup_journey_timeline": [
                {
                    "summary": event.summary,
                    "event_date": event.event_date.isoformat() if event.event_date else None,
                    "confidence": event.confidence,
                    "citations": event.citations,
                }
                for event in event_rows[:20]
            ],
            "core_themes": theme_list,
            "notable_quotes": [
                {
                    "speaker": quote.speaker,
                    "quote_text": quote.quote_text,
                    "confidence": quote.confidence,
                    "citations": quote.citations,
                }
                for quote in quote_rows[:12]
            ],
            "supported_claims": [
                {
                    "statement": claim.statement,
                    "confidence": claim.confidence,
                    "citations": claim.citations,
                }
                for claim in sorted(claim_rows, key=lambda claim: claim.confidence, reverse=True)[:20]
            ],
            "source_coverage": {
                "by_platform": dict(coverage),
                "failed_source_ids": [source.id for source in failed_sources],
            },
            "open_questions": open_questions,
        },
        citation_map=citation_map,
    )
    session.add(dossier)
    session.flush()
    return dossier

