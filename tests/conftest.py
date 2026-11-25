import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def offline_mode(monkeypatch):
    """Every test starts in local mode with no API key and no .env influence."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("RUPEE_LEDGER_DB", raising=False)


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "test.db")


@pytest.fixture
def client(app):
    return app.test_client()
