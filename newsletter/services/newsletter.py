"""
write_newsletter skill: turn a founder's knowledge sandbox into an engaging,
grounded newsletter about their startup journey.

The engine is a 3-step parser -> writer -> reviewer pipeline (generator-critic-
refiner), each step a separate Claude call:

  1. Parser   retrieved chunks (+ dossier, if any) -> structured story brief
  2. Writer   story brief -> engaging markdown draft
  3. Reviewer draft -> critique against a rubric -> final markdown (1 revision)

Everything is grounded strictly in material retrieved from Qdrant, filtered by
subject_id (the founder sandbox). Output is markdown, returned and saved to disk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.config import get_settings
from newsletter.models import Dossier, Subject
from newsletter.services.vector import search as vector_search
from newsletter.services.writer import build_writer_packet

logger = logging.getLogger(__name__)

# Themed queries to pull broad coverage of the whole arc, not one slice.
RETRIEVAL_QUERIES = [
    "early life, background, and how they got started",
    "the founding story and why they started the company",
    "biggest challenges, setbacks, and pivots",
    "product, growth, and key milestones",
    "vision, philosophy, and lessons learned",
]
PER_QUERY_LIMIT = 6
TARGET_WORDS = "800-1200"
MAX_TOKENS = 4096


@lru_cache(maxsize=1)
def _anthropic():
    from anthropic import Anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=settings.anthropic_api_key)


def _complete(system: str, user: str) -> str:
    settings = get_settings()
    client = _anthropic()
    resp = client.messages.create(
        model=settings.newsletter_model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()


def _retrieve_context(subject_id: str) -> list[str]:
    """Run themed queries, dedupe chunks by id, return their texts."""
    seen: dict[str, str] = {}
    for query in RETRIEVAL_QUERIES:
        try:
            results = vector_search(query, subject_id=subject_id, limit=PER_QUERY_LIMIT)
        except Exception as exc:
            logger.warning("vector search failed for %r: %s", query, exc)
            continue
        for r in results:
            if r.text and r.chunk_id not in seen:
                seen[r.chunk_id] = r.text
    return list(seen.values())


def _latest_dossier(session: Session, subject_id: str) -> Dossier | None:
    return session.scalars(
        select(Dossier)
        .where(Dossier.subject_id == subject_id)
        .order_by(Dossier.version.desc())
    ).first()


def _dossier_highlights(subject: Subject, dossier: Dossier) -> str:
    """High-signal structured input from the dossier: quotes + timeline."""
    packet = build_writer_packet(
        subject=subject, dossier=dossier, max_claims=12, max_quotes=10, max_events=15
    )
    lines: list[str] = []
    if packet.timeline:
        lines.append("Timeline:")
        for event in packet.timeline:
            when = event.get("date") or event.get("when") or ""
            what = event.get("description") or event.get("title") or event.get("text") or ""
            lines.append(f"- {when} {what}".strip())
    if packet.notable_quotes:
        lines.append("\nNotable quotes:")
        for q in packet.notable_quotes:
            speaker = q.get("speaker") or subject.name
            text = q.get("quote_text") or q.get("text") or ""
            if text:
                lines.append(f'- {speaker}: "{text}"')
    if packet.core_themes:
        lines.append("\nCore themes: " + ", ".join(packet.core_themes))
    return "\n".join(lines).strip()


def _parse(subject: Subject, chunks: list[str], dossier_highlights: str) -> str:
    company = f" ({subject.company_name})" if subject.company_name else ""
    system = (
        "You are a research editor preparing a story brief for a founder newsletter. "
        "Work ONLY from the supplied material below. Never invent facts, dates, or "
        "quotes; if something is missing, note the gap instead of filling it."
    )
    parts = [
        f"Founder: {subject.name}{company}",
        "\nProduce a structured story brief in markdown with these sections:",
        "- **Hook angle**: the single most compelling thread of their story",
        "- **Beats**: 4-6 chronological beats of the startup journey",
        "- **Themes**: 2-3 core themes",
        "- **Quotes**: the strongest verbatim quotes, with attribution",
        "- **Lessons**: key takeaways a reader could apply",
    ]
    if dossier_highlights:
        parts.append("\n## Structured highlights\n" + dossier_highlights)
    if chunks:
        parts.append("\n## Source excerpts\n" + "\n\n---\n\n".join(chunks))
    else:
        parts.append("\n## Source excerpts\n(none retrieved — say so plainly)")
    return _complete(system, "\n".join(parts))


def _write(subject: Subject, brief: str) -> str:
    company = f" ({subject.company_name})" if subject.company_name else ""
    system = (
        "You are a sharp newsletter writer. Turn the story brief into an engaging, "
        f"~{TARGET_WORDS}-word newsletter in markdown about a founder's startup journey. "
        "Open with a strong hook, use skimmable subheads, weave in real quotes verbatim, "
        "and close with a takeaway. Stay strictly grounded in the brief — do not add "
        "facts or quotes that are not present. Output only the newsletter markdown."
    )
    user = f"Founder: {subject.name}{company}\n\n## Story brief\n{brief}"
    return _complete(system, user)


def _review(subject: Subject, brief: str, draft: str) -> str:
    system = (
        "You are a demanding newsletter editor. Improve the draft against this rubric:\n"
        "- Hook: does the opening earn the next paragraph?\n"
        "- Grounding: every fact and quote must trace to the brief; cut anything invented.\n"
        "- Structure: skimmable subheads, tight paragraphs, clear arc.\n"
        "- Voice: consistent, engaging, not generic AI filler.\n"
        "Return the improved final newsletter in markdown. Output only the markdown — "
        "no commentary, no critique notes."
    )
    user = (
        f"Founder: {subject.name}\n\n## Story brief (source of truth)\n{brief}"
        f"\n\n## Draft to improve\n{draft}"
    )
    return _complete(system, user)


def _save(subject_id: str, markdown: str) -> Path:
    settings = get_settings()
    out_dir = Path(settings.object_store_root) / "newsletters"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{subject_id}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def write_newsletter(session: Session, subject_id: str) -> str:
    """Generate and persist a newsletter for a founder; returns the markdown."""
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise ValueError(f"Subject {subject_id} not found")

    chunks = _retrieve_context(subject_id)
    dossier = _latest_dossier(session, subject_id)
    highlights = _dossier_highlights(subject, dossier) if dossier else ""

    brief = _parse(subject, chunks, highlights)
    draft = _write(subject, brief)
    final = _review(subject, brief, draft)
    if not final:
        final = draft or "(no newsletter generated)"

    path = _save(subject_id, final)
    logger.info("Wrote newsletter for %s to %s", subject_id, path)
    return final
