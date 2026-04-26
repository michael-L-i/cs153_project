from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsletter.config import reset_settings_cache
from newsletter.db import reset_engine_cache


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("DEFAULT_RESEARCH_JOB_MODE", "inline")
    reset_settings_cache()
    reset_engine_cache()

    from newsletter.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

