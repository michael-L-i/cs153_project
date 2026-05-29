"""
write_newsletter skill: turn a founder's knowledge sandbox into an engaging,
grounded newsletter about their startup journey.

The engine is a 3-step researcher -> writer -> reviewer pipeline:

  1. Researcher  an agentic tool-use loop: Claude drives `search_founder`
                 (hybrid retrieval over Qdrant) for itself, following threads
                 across the founder's story, and returns a structured brief —
                 a hook, a causal narrative spine, themes, a verbatim quote
                 bank (with source provenance), and lessons.
  2. Writer      brief -> engaging markdown draft, quotes woven in verbatim.
  3. Reviewer    draft -> critique against a rubric -> final markdown (1 revision)

Everything is grounded strictly in material retrieved from Qdrant, filtered by
subject_id (the founder sandbox) — the agent never picks the subject; it is
bound server-side on every search. The markdown is returned and also saved as a
JSON file under the repo's ./newsletters dir, one file per founder.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.config import get_settings
from newsletter.models import Dossier, Source, Subject
from newsletter.services.vector import search as vector_search
from newsletter.services.writer import build_writer_packet

logger = logging.getLogger(__name__)

PER_QUERY_LIMIT = 6
TARGET_WORDS = "800-1200"
MAX_TOKENS = 4096

# The researcher drives retrieval itself via this tool. subject_id is NOT a
# parameter — it is bound server-side so the agent can only ever search inside
# one founder's sandbox.
SEARCH_TOOL = {
    "name": "search_founder",
    "description": (
        "Semantic + keyword search over everything the founder has said or that "
        "has been written about them — interview transcripts, talks, articles, "
        "posts. Returns the most relevant passages, each tagged with its source. "
        "Call this repeatedly to explore the founder's whole story: start broad, "
        "then follow threads — when a passage hints at a bigger moment (a pivot, "
        "a failure, a vivid anecdote, a strong or contrarian opinion), search "
        "again for that specific thing to pull the full quote and its context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for, in natural language.",
            },
            "source_type": {
                "type": "string",
                "description": (
                    "Optional filter. Use 'youtube_transcript' or 'x_post' to "
                    "surface first-person statements in the founder's own voice; "
                    "'website' for articles and interviews. Omit to search all."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max passages to return (1-10). Defaults to 6.",
            },
        },
        "required": ["query"],
    },
}

# Hard cap on tool calls so cost/latency are bounded; on the last turn we force
# the model to stop searching and write the brief.
MAX_SEARCHES = 10

RESEARCH_SYSTEM = (
    "You are a research editor mining a founder's knowledge sandbox to build the "
    "brief for an engaging newsletter about their startup journey. You have a "
    "search_founder tool — use it to read widely, then dig: cover the whole arc "
    "(origins, the founding decision, setbacks and pivots, growth and milestones, "
    "current vision), and whenever a passage hints at a richer story, search again "
    "to pull the full anecdote and the exact words. Favor the founder's own voice "
    "for quotes (transcripts and posts). Typically 5-9 searches is enough; once you "
    "have rich material, STOP searching and write the brief.\n\n"
    "Work ONLY from what the tool returns. Never invent facts, dates, or quotes; "
    "every quote in the bank must be a verbatim span you actually saw, and note "
    "gaps instead of filling them.\n\n"
    "Output ONLY the final brief in markdown, with these sections:\n"
    "- **Hook**: the single most compelling thread of their story.\n"
    "- **Narrative spine**: 5-8 ordered beats forming a causal arc — each beat is "
    "an event and its consequence (what happened -> what it led to), so the story "
    "reads as a chain, not a list.\n"
    "- **Themes**: 2-3 core themes.\n"
    "- **Quote bank**: the strongest VERBATIM quotes (copy them exactly). For each, "
    "give: the quote, the speaker, and one line of context (what was happening / why "
    "it matters) with its source descriptor.\n"
    "- **Lessons**: takeaways a reader could apply."
)


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


def _source_descriptor(source: Source | None) -> str:
    """Compact provenance tag for a retrieved passage, e.g.
    'youtube_transcript · "How I Built Acme" · 2021'."""
    if source is None:
        return "unknown source"
    bits: list[str] = [source.source_type or source.platform or "source"]
    if source.title:
        bits.append(f'"{source.title}"')
    if source.author:
        bits.append(source.author)
    if source.published_at:
        bits.append(str(source.published_at.year))
    return " · ".join(bits)


def _run_search(
    session: Session,
    subject_id: str,
    source_cache: dict[str, Source],
    args: dict,
) -> str:
    """Execute one search_founder call, scoped to the founder, with provenance.

    subject_id is injected here, never taken from `args` — the agent cannot
    search outside its sandbox.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: 'query' is required."
    source_type = args.get("source_type") or None
    try:
        limit = int(args.get("limit") or PER_QUERY_LIMIT)
    except (TypeError, ValueError):
        limit = PER_QUERY_LIMIT
    limit = max(1, min(limit, 10))

    try:
        results = vector_search(
            query, subject_id=subject_id, source_type=source_type, limit=limit
        )
    except Exception as exc:
        logger.warning("search_founder failed for %r: %s", query, exc)
        return f"Search failed: {exc}"
    if not results:
        return "No passages found for that query."

    missing = {r.source_id for r in results if r.source_id and r.source_id not in source_cache}
    if missing:
        for src in session.scalars(select(Source).where(Source.id.in_(missing))).all():
            source_cache[src.id] = src

    blocks = [
        f"[{_source_descriptor(source_cache.get(r.source_id))}]\n{r.text}"
        for r in results
        if r.text
    ]
    return "\n\n---\n\n".join(blocks) if blocks else "No passages found for that query."


def _research(session: Session, subject: Subject, seed: str) -> str:
    """Agentic research loop: Claude drives search_founder, then returns a brief."""
    company = f" ({subject.company_name})" if subject.company_name else ""
    kickoff = [f"Founder: {subject.name}{company}"]
    if seed:
        kickoff.append(
            "\nA prior pass surfaced these structured highlights — use them as "
            "leads to search against, not as the final brief:\n" + seed
        )
    kickoff.append("\nResearch the founder with search_founder, then write the brief.")

    system = [{"type": "text", "text": RESEARCH_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": "\n".join(kickoff)}]
    source_cache: dict[str, Source] = {}

    settings = get_settings()
    client = _anthropic()
    searches = 0

    while True:
        force_finish = searches >= MAX_SEARCHES
        resp = client.messages.create(
            model=settings.newsletter_model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=[SEARCH_TOOL],
            tool_choice={"type": "none"} if force_finish else {"type": "auto"},
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                searches += 1
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _run_search(session, subject.id, source_cache, block.input or {}),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()


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


def _write(subject: Subject, brief: str) -> str:
    company = f" ({subject.company_name})" if subject.company_name else ""
    system = (
        "You are a sharp newsletter writer. Turn the story brief into an engaging, "
        f"~{TARGET_WORDS}-word newsletter in markdown about a founder's startup journey. "
        "Build the arc from the Narrative spine so the piece reads as one cohesive "
        "story, not a list of facts. Open with a strong hook, use skimmable subheads, "
        "and weave in quotes from the Quote bank VERBATIM — copy them exactly, never "
        "paraphrase a quote — with just enough context to land. Close with a takeaway. "
        "Stay strictly grounded in the brief — do not add facts or quotes that are not "
        "present. Output only the newsletter markdown."
    )
    user = f"Founder: {subject.name}{company}\n\n## Story brief\n{brief}"
    return _complete(system, user)


def _review(subject: Subject, brief: str, draft: str) -> str:
    system = (
        "You are a demanding newsletter editor. Improve the draft against this rubric:\n"
        "- Hook: does the opening earn the next paragraph?\n"
        "- Cohesion: the story follows the brief's narrative spine as a causal arc.\n"
        "- Grounding: every fact and quote must trace to the brief; cut anything invented.\n"
        "- Quotes: any quoted text must appear VERBATIM in the brief's quote bank; fix "
        "or cut quotes that were paraphrased or altered.\n"
        "- Structure: skimmable subheads, tight paragraphs.\n"
        "- Voice: consistent, engaging, not generic AI filler.\n"
        "Return the improved final newsletter in markdown. Output only the markdown — "
        "no commentary, no critique notes."
    )
    user = (
        f"Founder: {subject.name}\n\n## Story brief (source of truth)\n{brief}"
        f"\n\n## Draft to improve\n{draft}"
    )
    return _complete(system, user)


# Newsletters are written into the repo (a tracked dir), not the gitignored
# object store, so generated output lives alongside the code.
NEWSLETTER_DIR = Path(__file__).resolve().parents[2] / "newsletters"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "founder"


def _save(subject: Subject, markdown: str) -> Path:
    NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)
    path = NEWSLETTER_DIR / f"{_slug(subject.name)}.json"
    payload = {
        "subject_id": subject.id,
        "name": subject.name,
        "company_name": subject.company_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markdown": markdown,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def write_newsletter(session: Session, subject_id: str) -> str:
    """Generate and persist a newsletter for a founder; returns the markdown."""
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise ValueError(f"Subject {subject_id} not found")

    dossier = _latest_dossier(session, subject_id)
    highlights = _dossier_highlights(subject, dossier) if dossier else ""

    brief = _research(session, subject, highlights)
    draft = _write(subject, brief)
    final = _review(subject, brief, draft)
    if not final:
        final = draft or "(no newsletter generated)"

    path = _save(subject, final)
    logger.info("Wrote newsletter for %s to %s", subject_id, path)
    return final
