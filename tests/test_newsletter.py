from __future__ import annotations

from pathlib import Path

import pytest

from newsletter.config import reset_settings_cache
from newsletter.db import reset_engine_cache


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, scripted: list[str], calls: list[dict]) -> None:
        self._scripted = scripted
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        idx = min(len(self._calls) - 1, len(self._scripted) - 1)
        return _Resp(self._scripted[idx])


class _FakeAnthropic:
    def __init__(self, scripted: list[str], calls: list[dict]) -> None:
        self.messages = _FakeMessages(scripted, calls)


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    reset_settings_cache()
    reset_engine_cache()

    from newsletter.db import create_db_and_tables, get_session_factory

    create_db_and_tables()
    s = get_session_factory()()
    try:
        yield s
    finally:
        s.close()


def _make_subject(session) -> str:
    from newsletter.models import Subject

    subject = Subject(name="Jane Founder", company_name="Acme")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject.id


def _patch_pipeline(monkeypatch, scripted: list[str]) -> tuple[list[str], list[dict]]:
    from newsletter.services import newsletter as svc
    from newsletter.services.vector import SearchResult

    queries: list[str] = []

    def fake_search(query, *, subject_id=None, source_type=None, limit=8):
        queries.append(query)
        return [
            SearchResult(
                chunk_id=f"{query[:5]}-{i}",
                score=1.0,
                text=f"excerpt about {query}",
                subject_id=subject_id or "",
                source_id="src",
                source_type="article",
                source_url="https://example.com",
                metadata={},
            )
            for i in range(2)
        ]

    calls: list[dict] = []
    monkeypatch.setattr(svc, "vector_search", fake_search)
    monkeypatch.setattr(svc, "_anthropic", lambda: _FakeAnthropic(scripted, calls))
    return queries, calls


def test_write_newsletter_runs_pipeline_and_saves(session, monkeypatch, tmp_path):
    subject_id = _make_subject(session)
    queries, calls = _patch_pipeline(
        monkeypatch, ["BRIEF-OUTPUT", "DRAFT-OUTPUT", "# Final Newsletter"]
    )

    from newsletter.services.newsletter import write_newsletter

    result = write_newsletter(session, subject_id)

    # Reviewer output is what's returned.
    assert result == "# Final Newsletter"
    # Three Claude calls: parser, writer, reviewer.
    assert len(calls) == 3
    # Broad retrieval ran one query per theme.
    assert len(queries) == 5
    # Writer received the parser's brief; reviewer received the draft.
    assert "BRIEF-OUTPUT" in calls[1]["messages"][0]["content"]
    assert "DRAFT-OUTPUT" in calls[2]["messages"][0]["content"]
    # File persisted under object store.
    saved = list((tmp_path / "objects" / "newsletters").glob(f"{subject_id}-*.md"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == "# Final Newsletter"


def test_write_newsletter_falls_back_to_draft_when_review_empty(session, monkeypatch):
    subject_id = _make_subject(session)
    _patch_pipeline(monkeypatch, ["BRIEF", "DRAFT-OUTPUT", ""])

    from newsletter.services.newsletter import write_newsletter

    assert write_newsletter(session, subject_id) == "DRAFT-OUTPUT"


def test_write_newsletter_unknown_subject_raises(session, monkeypatch):
    _patch_pipeline(monkeypatch, ["x"])

    from newsletter.services.newsletter import write_newsletter

    with pytest.raises(ValueError):
        write_newsletter(session, "does-not-exist")
