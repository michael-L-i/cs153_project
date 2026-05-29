from __future__ import annotations

import pytest

from newsletter.auth import AuthUser, get_current_user
from newsletter.services import chat as chat_service


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp("ASSISTANT REPLY")


class _FakeAnthropic:
    def __init__(self, calls: list) -> None:
        self.messages = _FakeMessages(calls)


@pytest.fixture
def chat_client(client, monkeypatch):
    """API client with auth stubbed to a fixed user and the LLM/RAG stubbed out."""
    calls: list = []
    monkeypatch.setattr(chat_service, "_anthropic", lambda: _FakeAnthropic(calls))
    monkeypatch.setattr(chat_service, "_retrieve_context", lambda *a, **k: [])
    monkeypatch.setattr(chat_service, "_recall_memories", lambda *a, **k: [])
    monkeypatch.setattr(chat_service, "_remember", lambda *a, **k: None)

    client.app.dependency_overrides[get_current_user] = lambda: AuthUser(id="user-1", email="u@example.com")
    client._llm_calls = calls
    return client


def _make_subject(client) -> str:
    res = client.post("/subjects", json={"name": "Jane Founder", "company_name": "Acme"})
    assert res.status_code == 200
    return res.json()["id"]


def test_conversation_lifecycle_and_context_scoping(chat_client):
    sid = _make_subject(chat_client)

    # No conversations yet.
    res = chat_client.get(f"/founders/{sid}/conversations")
    assert res.status_code == 200
    assert res.json()["conversations"] == []

    # Create one.
    res = chat_client.post(f"/founders/{sid}/conversations", json={})
    assert res.status_code == 200
    conv_a = res.json()["id"]

    # Untitled until first message.
    assert chat_client.get(f"/founders/{sid}/conversations").json()["conversations"][0]["title"] == "New conversation"

    # Send two messages.
    assert chat_client.post(f"/founders/{sid}/conversations/{conv_a}/chat", json={"message": "Hello there"}).status_code == 200
    assert chat_client.post(f"/founders/{sid}/conversations/{conv_a}/chat", json={"message": "Second one"}).status_code == 200

    # First user message becomes the title.
    assert chat_client.get(f"/founders/{sid}/conversations").json()["conversations"][0]["title"] == "Hello there"

    # Messages are persisted in order (2 user + 2 assistant).
    msgs = chat_client.get(f"/founders/{sid}/conversations/{conv_a}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "Hello there"

    # A brand-new conversation does NOT see the first one's turns (context reset).
    conv_b = chat_client.post(f"/founders/{sid}/conversations", json={}).json()["id"]
    chat_client._llm_calls.clear()
    chat_client.post(f"/founders/{sid}/conversations/{conv_b}/chat", json={"message": "Fresh start"})
    sent = chat_client._llm_calls[-1]["messages"]
    assert sent == [{"role": "user", "content": "Fresh start"}]  # only this turn, no history from conv_a

    # Two conversations now exist for this founder.
    assert len(chat_client.get(f"/founders/{sid}/conversations").json()["conversations"]) == 2


def test_rename_and_delete(chat_client):
    sid = _make_subject(chat_client)
    cid = chat_client.post(f"/founders/{sid}/conversations", json={}).json()["id"]

    res = chat_client.patch(f"/founders/{sid}/conversations/{cid}", json={"title": "Pricing questions"})
    assert res.status_code == 200 and res.json()["title"] == "Pricing questions"

    assert chat_client.delete(f"/founders/{sid}/conversations/{cid}").status_code == 200
    assert chat_client.get(f"/founders/{sid}/conversations").json()["conversations"] == []
    # Messages of a deleted conversation are gone (404).
    assert chat_client.get(f"/founders/{sid}/conversations/{cid}/messages").status_code == 404


def test_ownership_is_enforced(chat_client):
    sid = _make_subject(chat_client)
    cid = chat_client.post(f"/founders/{sid}/conversations", json={}).json()["id"]

    # Switch to a different user.
    chat_client.app.dependency_overrides[get_current_user] = lambda: AuthUser(id="user-2", email="other@example.com")

    assert chat_client.get(f"/founders/{sid}/conversations/{cid}/messages").status_code == 403
    assert chat_client.post(f"/founders/{sid}/conversations/{cid}/chat", json={"message": "hi"}).status_code == 403
    # And user-2 sees none of user-1's conversations.
    assert chat_client.get(f"/founders/{sid}/conversations").json()["conversations"] == []
