from __future__ import annotations

from pathlib import Path

import pytest

from newsletter.config import reset_settings_cache
from newsletter.db import reset_engine_cache


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _ToolUseBlock:
    def __init__(self, block_id: str, name: str, tool_input: dict) -> None:
        self.type = "tool_use"
        self.id = block_id
        self.name = name
        self.input = tool_input


class _Resp:
    def __init__(self, content: list, stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


def _text_resp(text: str) -> _Resp:
    return _Resp([_TextBlock(text)], "end_turn")


def _tool_resp(calls: list[dict]) -> _Resp:
    blocks = [
        _ToolUseBlock(f"toolu_{i}", c.get("name", "search_founder"), c.get("input", {}))
        for i, c in enumerate(calls)
    ]
    return _Resp(blocks, "tool_use")


class _FakeMessages:
    """Scripts a sequence of responses. A request with tool_choice 'none'
    (the research loop's forced-finish turn) always yields a text brief,
    modeling a model that can no longer call tools."""

    def __init__(self, scripted: list, calls: list[dict]) -> None:
        self._scripted = scripted
        self._calls = calls

    def create(self, **kwargs):
        # Index off the shared calls list so the script survives the fresh
        # client instances _complete() creates via _anthropic().
        idx = len(self._calls)
        self._calls.append(kwargs)
        if kwargs.get("tool_choice") == {"type": "none"}:
            return _text_resp("CAPPED-BRIEF")
        item = self._scripted[min(idx, len(self._scripted) - 1)]
        if isinstance(item, dict) and item.get("kind") == "tool_use":
            return _tool_resp(item["calls"])
        return _text_resp(item if isinstance(item, str) else item.get("text", ""))


class _FakeAnthropic:
    def __init__(self, scripted: list, calls: list[dict]) -> None:
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


def _patch_pipeline(monkeypatch, tmp_path, scripted: list):
    """Patch retrieval, the Anthropic client, and the output dir.

    Returns (searches, calls): searches records each search_founder invocation
    (query + subject_id); calls records each Anthropic request.
    """
    from newsletter.services import newsletter as svc
    from newsletter.services.vector import SearchResult

    searches: list[dict] = []

    def fake_search(query, *, subject_id=None, source_type=None, limit=8):
        searches.append({"query": query, "subject_id": subject_id, "source_type": source_type})
        return [
            SearchResult(
                chunk_id=f"{query[:5]}-{i}",
                score=1.0,
                text=f"excerpt about {query}",
                subject_id=subject_id or "",
                source_id="src",
                source_type="website",
                source_url="https://example.com",
                metadata={},
            )
            for i in range(2)
        ]

    calls: list[dict] = []
    monkeypatch.setattr(svc, "vector_search", fake_search)
    monkeypatch.setattr(svc, "_anthropic", lambda: _FakeAnthropic(scripted, calls))
    monkeypatch.setattr(svc, "NEWSLETTER_DIR", tmp_path / "newsletters")
    return searches, calls


def test_write_newsletter_runs_pipeline_and_saves(session, monkeypatch, tmp_path):
    subject_id = _make_subject(session)
    scripted = [
        {"kind": "tool_use", "calls": [{"input": {"query": "founding story"}}]},
        "BRIEF-OUTPUT",   # research brief (end_turn)
        "DRAFT-OUTPUT",   # writer
        "# Final Newsletter",  # reviewer
    ]
    searches, calls = _patch_pipeline(monkeypatch, tmp_path, scripted)

    from newsletter.services.newsletter import write_newsletter

    result = write_newsletter(session, subject_id)

    # Reviewer output is what's returned.
    assert result == "# Final Newsletter"
    # 4 Claude calls: research tool turn, research brief, writer, reviewer.
    assert len(calls) == 4
    # The agent searched once; subject_id was injected, not model-supplied.
    assert len(searches) == 1
    assert searches[0]["query"] == "founding story"
    assert searches[0]["subject_id"] == subject_id
    # Brief flowed to the writer; draft flowed to the reviewer.
    assert "BRIEF-OUTPUT" in calls[2]["messages"][0]["content"]
    assert "DRAFT-OUTPUT" in calls[3]["messages"][0]["content"]
    # The research turn advertised the search tool and cached the system prompt.
    assert calls[0]["tools"][0]["name"] == "search_founder"
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Persisted as <slug>.json in the newsletters dir.
    saved = list((tmp_path / "newsletters").glob("jane-founder.json"))
    assert len(saved) == 1


def test_research_loop_caps_searches(session, monkeypatch, tmp_path):
    from newsletter.services import newsletter as svc

    subject_id = _make_subject(session)
    # Model keeps requesting a tool every turn; the loop must force-finish.
    scripted = [{"kind": "tool_use", "calls": [{"input": {"query": "again"}}]}]
    searches, calls = _patch_pipeline(monkeypatch, tmp_path, scripted)

    from newsletter.services.newsletter import write_newsletter

    write_newsletter(session, subject_id)

    # Search count is capped; the forced-finish turn produced the brief.
    assert len(searches) == svc.MAX_SEARCHES
    assert calls[svc.MAX_SEARCHES]["tool_choice"] == {"type": "none"}


def test_write_newsletter_falls_back_to_draft_when_review_empty(session, monkeypatch, tmp_path):
    subject_id = _make_subject(session)
    scripted = [
        {"kind": "tool_use", "calls": [{"input": {"query": "x"}}]},
        "BRIEF",
        "DRAFT-OUTPUT",
        "",  # reviewer returns nothing
    ]
    _patch_pipeline(monkeypatch, tmp_path, scripted)

    from newsletter.services.newsletter import write_newsletter

    assert write_newsletter(session, subject_id) == "DRAFT-OUTPUT"


def test_write_newsletter_unknown_subject_raises(session, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, tmp_path, ["x"])

    from newsletter.services.newsletter import write_newsletter

    with pytest.raises(ValueError):
        write_newsletter(session, "does-not-exist")
