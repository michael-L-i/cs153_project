"""
Per-founder chat: RAG over Qdrant + Mem0 long-term memory + Claude.

The founder's knowledge sandbox lives in Qdrant (filtered by subject_id).
Mem0 stores the *user's* side of the conversation — facts about Michael,
preferences, prior topics — scoped to (user_id, agent_id=subject_id).
Recent raw turns come from Postgres for short-term continuity.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.config import get_settings
from newsletter.models import Conversation, Message, Subject, utc_now
from newsletter.services.vector import search as vector_search

logger = logging.getLogger(__name__)

RECENT_TURNS = 20
RAG_LIMIT = 6
MEM0_LIMIT = 5


@lru_cache(maxsize=1)
def _anthropic():
    from anthropic import Anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=settings.anthropic_api_key)


@lru_cache(maxsize=1)
def _mem0():
    from mem0 import MemoryClient
    settings = get_settings()
    if not settings.mem0_api_key:
        return None
    return MemoryClient(api_key=settings.mem0_api_key)


def _recent_turns(session: Session, conversation_id: str, limit: int = RECENT_TURNS) -> list[Message]:
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def _retrieve_context(subject_id: str, message: str) -> list[str]:
    try:
        results = vector_search(message, subject_id=subject_id, limit=RAG_LIMIT)
    except Exception as exc:
        logger.warning("vector search failed: %s", exc)
        return []
    return [r.text for r in results if r.text]


def _recall_memories(user_id: str, agent_id: str, message: str) -> list[str]:
    client = _mem0()
    if client is None:
        return []
    try:
        results = client.search(
            query=message,
            version="v2",
            filters={"AND": [{"user_id": user_id}, {"agent_id": agent_id}]},
            limit=MEM0_LIMIT,
        )
    except Exception as exc:
        logger.warning("mem0 search failed: %s", exc)
        return []
    # hosted Mem0 returns a list of {"memory": "...", ...} dicts
    out = []
    for item in results or []:
        if isinstance(item, dict):
            text = item.get("memory") or item.get("text")
            if text:
                out.append(text)
    return out


def _remember(user_id: str, agent_id: str, user_message: str, assistant_reply: str) -> None:
    client = _mem0()
    if client is None:
        return
    try:
        client.add(
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_reply},
            ],
            user_id=user_id,
            agent_id=agent_id,
        )
    except Exception as exc:
        logger.warning("mem0 add failed: %s", exc)


def _build_system_prompt(subject: Subject, chunks: list[str], memories: list[str]) -> str:
    company = f" ({subject.company_name})" if subject.company_name else ""
    parts = [
        f"You are speaking as {subject.name}{company}. Respond in the first person, in their voice, "
        "grounded strictly in the source excerpts below. If the excerpts do not cover what is asked, "
        "say so plainly rather than inventing detail. Keep replies conversational and concise.",
    ]
    if memories:
        parts.append("\n## What you remember about the person you're talking to\n" + "\n".join(f"- {m}" for m in memories))
    if chunks:
        parts.append("\n## Source excerpts from your interviews, writing, and talks\n" + "\n\n---\n\n".join(chunks))
    else:
        parts.append("\n## Source excerpts\n(none retrieved — be honest about the gap)")
    return "\n".join(parts)


def _title_from(message: str) -> str:
    title = " ".join((message or "").split())
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return title or "New conversation"


def _generate_title(message: str, reply: str) -> str:
    """Ask a fast model for a short, descriptive thread title.

    Falls back to a truncation of the first user message on any error so titling
    can never break the chat flow.
    """
    settings = get_settings()
    try:
        resp = _anthropic().messages.create(
            model=settings.anthropic_title_model,
            max_tokens=24,
            system=(
                "Generate a concise, specific title (3-6 words) for a chat conversation, "
                "based on the user's first message and the reply. Reply with ONLY the title — "
                "no quotes, no surrounding punctuation, no trailing period."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"First message:\n{message}\n\nReply:\n{reply}\n\nTitle:",
                }
            ],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        title = " ".join(raw.split()).strip().strip('"').strip("'").rstrip(".").strip()
        if len(title) > 60:
            title = title[:57].rstrip() + "…"
        return title or _title_from(message)
    except Exception as exc:  # noqa: BLE001 — titling must never break chat
        logger.warning("title generation failed: %s", exc)
        return _title_from(message)


def _get_owned_conversation(session: Session, conversation_id: str, user_id: str) -> Conversation:
    """Load a conversation, raising if it doesn't exist or isn't owned by user_id."""
    convo = session.get(Conversation, conversation_id)
    if convo is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    if convo.user_id != user_id:
        raise PermissionError("Conversation belongs to another user")
    return convo


def create_conversation(session: Session, subject_id: str, user_id: str, title: str | None = None) -> Conversation:
    if session.get(Subject, subject_id) is None:
        raise ValueError(f"Subject {subject_id} not found")
    convo = Conversation(subject_id=subject_id, user_id=user_id, title=title)
    session.add(convo)
    session.commit()
    session.refresh(convo)
    return convo


def list_conversations(session: Session, subject_id: str, user_id: str) -> list[Conversation]:
    return list(
        session.scalars(
            select(Conversation)
            .where(Conversation.subject_id == subject_id, Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        ).all()
    )


def rename_conversation(session: Session, conversation_id: str, user_id: str, title: str) -> Conversation:
    convo = _get_owned_conversation(session, conversation_id, user_id)
    convo.title = title.strip() or convo.title
    session.commit()
    session.refresh(convo)
    return convo


def delete_conversation(session: Session, conversation_id: str, user_id: str) -> None:
    convo = _get_owned_conversation(session, conversation_id, user_id)
    session.delete(convo)
    session.commit()


def respond(session: Session, conversation_id: str, message: str, user_id: str) -> str:
    settings = get_settings()

    convo = _get_owned_conversation(session, conversation_id, user_id)
    subject = session.get(Subject, convo.subject_id)
    if subject is None:
        raise ValueError(f"Subject {convo.subject_id} not found")

    history = _recent_turns(session, conversation_id)
    chunks = _retrieve_context(subject.id, message)
    memories = _recall_memories(user_id, subject.id, message)
    system = _build_system_prompt(subject, chunks, memories)

    messages = [{"role": c.role, "content": c.content} for c in history]
    messages.append({"role": "user", "content": message})

    client = _anthropic()
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    reply = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text").strip()
    if not reply:
        reply = "(no reply)"

    session.add(Message(conversation_id=conversation_id, subject_id=subject.id, user_id=user_id, role="user", content=message))
    session.add(Message(conversation_id=conversation_id, subject_id=subject.id, user_id=user_id, role="assistant", content=reply))
    # First exchange names the conversation (LLM-generated); bump updated_at so it sorts up.
    if not convo.title:
        convo.title = _generate_title(message, reply)
    convo.updated_at = utc_now()
    session.commit()

    _remember(user_id, subject.id, message, reply)
    return reply


def list_messages(session: Session, conversation_id: str, user_id: str, limit: int = 200) -> list[Message]:
    _get_owned_conversation(session, conversation_id, user_id)
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))
