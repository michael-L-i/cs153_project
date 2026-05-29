"""One-time migration: flat message log -> Conversation (thread) + Message.

Before this change the `conversations` table was really a flat message log — one row
per turn, keyed by (subject_id, user_id). This script reshapes it into the standard
two-layer model the new chat UI expects:

    conversations  (thread / container)   id, subject_id, user_id, title, timestamps
    messages       (the old table)        + conversation_id pointer

It is idempotent and works on both SQLite and Postgres (Supabase). Existing history is
preserved: every (founder, user) with old messages gets one "default" conversation that
those messages are attached to. Running it again is a no-op.

Run from the repo root:

    python -m scripts.migrate_add_conversations
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect, text

from newsletter.db import Base, get_engine, get_session_factory
from newsletter.models import utc_now  # noqa: F401  (ensures models are imported for metadata)


def _title_from(content: str) -> str:
    title = " ".join((content or "").split())
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return title or "Conversation"


def migrate() -> None:
    engine = get_engine()

    # 1. Rename the old flat `conversations` (message log) -> `messages`.
    #    Identify the old schema by its `content` column; skip if already renamed.
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "content" in cols and "messages" not in tables:
            print("• renaming table conversations -> messages")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE conversations RENAME TO messages"))

    # 2. Create the new tables (the `conversations` container, and `messages` on a fresh
    #    install). create_all only creates what is missing — it never alters existing tables.
    Base.metadata.create_all(engine)

    # 3. Ensure `messages.conversation_id` exists (create_all won't add it to a table that
    #    already existed). ADD COLUMN IF NOT EXISTS isn't portable, so we inspect first.
    insp = inspect(engine)
    if "messages" in set(insp.get_table_names()):
        mcols = {c["name"] for c in insp.get_columns("messages")}
        if "conversation_id" not in mcols:
            print("• adding column messages.conversation_id")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages ADD COLUMN conversation_id VARCHAR(36)"))
    else:
        # No messages table at all (brand-new install) — nothing to backfill.
        print("• no messages table; fresh install, nothing to backfill")
        return

    # 4. Index the pointer (portable form is supported by both SQLite and Postgres).
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id)")
        )

    # 5. Backfill: one conversation per (subject_id, user_id) for orphaned messages.
    factory = get_session_factory()
    session = factory()
    try:
        groups = session.execute(
            text(
                "SELECT subject_id, user_id FROM messages "
                "WHERE conversation_id IS NULL "
                "GROUP BY subject_id, user_id"
            )
        ).all()

        if not groups:
            print("• no orphaned messages to backfill — already migrated")
            return

        for subject_id, user_id in groups:
            first = session.execute(
                text(
                    "SELECT content FROM messages "
                    "WHERE subject_id = :s AND user_id = :u AND conversation_id IS NULL "
                    "AND role = 'user' ORDER BY created_at ASC"
                ),
                {"s": subject_id, "u": user_id},
            ).first()
            title = _title_from(first[0]) if first else "Conversation"

            cid = str(uuid4())
            now = utc_now()
            session.execute(
                text(
                    "INSERT INTO conversations (id, subject_id, user_id, title, created_at, updated_at) "
                    "VALUES (:id, :s, :u, :t, :c, :c)"
                ),
                {"id": cid, "s": subject_id, "u": user_id, "t": title, "c": now},
            )
            result = session.execute(
                text(
                    "UPDATE messages SET conversation_id = :cid "
                    "WHERE subject_id = :s AND user_id = :u AND conversation_id IS NULL"
                ),
                {"cid": cid, "s": subject_id, "u": user_id},
            )
            print(f"• {subject_id[:8]}…/{user_id[:8]}…: {result.rowcount} message(s) -> conversation {cid[:8]}…")

        session.commit()
        print(f"✓ backfilled {len(groups)} conversation(s)")
    finally:
        session.close()


if __name__ == "__main__":
    migrate()
