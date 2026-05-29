"""Repair a half-applied conversation migration by resetting the schema (clean reset).

`scripts/migrate_add_conversations.py` assumed the new `messages` table would not yet
exist. In practice the app's `create_db_and_tables()` (run on startup) created an empty
`messages` table first, so the migration's rename guard was skipped and the live database
ended up in a broken intermediate state:

    conversations  -> still the OLD flat message-log schema (id, subject_id, user_id,
                      role, content, created_at) — missing `title` and `updated_at`
    messages       -> the NEW schema, but empty

In that state every conversation endpoint 500s with
`UndefinedColumn: column conversations.title does not exist`, and the old migration can no
longer recover (its rename is gated on `messages` not existing). This script supersedes it.

Per the decision to **discard old chat history**, it simply drops both tables and recreates
them from the current models so they match `Conversation`/`Message`. Idempotent and safe to
re-run on both SQLite and Postgres (Supabase).

Run from the repo root:

    python -m scripts.repair_conversations_schema
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from newsletter.db import Base, get_engine
from newsletter.models import utc_now  # noqa: F401  (ensures models are imported for metadata)


def repair() -> None:
    engine = get_engine()

    # Drop messages first — it carries a FK to conversations.
    with engine.begin() as conn:
        print("• dropping table messages (if it exists)")
        conn.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
        print("• dropping table conversations (if it exists)")
        conn.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))

    # Recreate both with the correct schema from newsletter.models.
    print("• recreating conversations + messages from models")
    Base.metadata.create_all(engine)

    # Confirm the resulting columns.
    insp = inspect(engine)
    for table in ("conversations", "messages"):
        cols = sorted(c["name"] for c in insp.get_columns(table))
        print(f"✓ {table}: {cols}")


if __name__ == "__main__":
    repair()
