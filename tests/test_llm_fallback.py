"""The optional OpenAI layer must never break the app."""
import pytest
import requests

import ai_engine


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def completion(text):
    return FakeResponse({"choices": [{"message": {"content": text}}]})


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")


FAILURES = [
    lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("slow")),
    lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    lambda *a, **k: FakeResponse(status=401),
    lambda *a, **k: FakeResponse(status=429),
    lambda *a, **k: FakeResponse(ValueError("not json")),
    lambda *a, **k: FakeResponse({"unexpected": True}),
    lambda *a, **k: FakeResponse({"choices": []}),
    lambda *a, **k: FakeResponse({"choices": [{"message": {"content": None}}]}),
    lambda *a, **k: completion("   "),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_every_failure_falls_back_to_local(with_key, monkeypatch, failure):
    monkeypatch.setattr(ai_engine.requests, "post", failure)
    assert ai_engine.ai_enabled()
    assert ai_engine.suggest_category("qqq zzz") == {"category": "Other", "confidence": 0.0, "source": "local"}
    rows = [{"amount": 500, "category": "Food & Dining", "description": "Swiggy", "expense_date": "2026-03-02"}]
    assert ai_engine.coach(rows, 0, "2026-03")["source"] == "local"
    answer = ai_engine.ask_assistant("how much on food", rows, 0, "2026-03")
    assert answer["source"] == "local" and "₹500.00" in answer["answer"]


def test_llm_results_are_used_when_available(with_key, monkeypatch):
    monkeypatch.setattr(ai_engine.requests, "post", lambda *a, **k: completion("Health"))
    assert ai_engine.suggest_category("qqq zzz") == {"category": "Health", "confidence": 0.85, "source": "llm"}
    rows = [{"amount": 500, "category": "Food & Dining", "description": "Swiggy", "expense_date": "2026-03-02"}]
    monkeypatch.setattr(ai_engine.requests, "post", lambda *a, **k: completion("You are doing great."))
    assert ai_engine.coach(rows, 0, "2026-03")["summary"] == "You are doing great."
    assert ai_engine.ask_assistant("anything", rows, 0, "2026-03") == {"answer": "You are doing great.", "source": "llm"}


def test_llm_category_must_be_valid(with_key, monkeypatch):
    monkeypatch.setattr(ai_engine.requests, "post", lambda *a, **k: completion("Cryptocurrency"))
    assert ai_engine.suggest_category("qqq zzz")["source"] == "local"


def test_llm_not_called_when_local_model_is_confident(with_key, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM should not be called")
    monkeypatch.setattr(ai_engine.requests, "post", boom)
    assert ai_engine.suggest_category("Swiggy biryani")["category"] == "Food & Dining"


def test_request_uses_timeout_and_configured_model(with_key, monkeypatch):
    seen = {}
    monkeypatch.setenv("OPENAI_MODEL", "my-model")

    def capture(url, **kwargs):
        seen.update(kwargs)
        return completion("Other")
    monkeypatch.setattr(ai_engine.requests, "post", capture)
    ai_engine.suggest_category("qqq zzz")
    assert seen["timeout"] == ai_engine.LLM_TIMEOUT
    assert seen["json"]["model"] == "my-model"
    assert seen["headers"]["Authorization"] == "Bearer sk-test-not-real"


def test_api_endpoints_survive_llm_outage(with_key, monkeypatch, client):
    monkeypatch.setattr(ai_engine.requests, "post", FAILURES[0])
    client.post("/api/expenses", json={"description": "Swiggy", "amount": 100, "expense_date": "2026-03-02"})
    assert client.post("/api/categorize", json={"description": "qqq"}).get_json()["source"] == "local"
    assert client.get("/api/coach?month=2026-03").get_json()["source"] == "local"
    r = client.post("/api/ask", json={"question": "total spent", "month": "2026-03"})
    assert r.status_code == 200 and r.get_json()["source"] == "local"
    # an unknown description is saved as Other even though the LLM is down
    e = client.post("/api/expenses", json={"description": "qqq zzz", "amount": 5}).get_json()["expense"]
    assert e["category"] == "Other"


def test_header_pill_reflects_key(client, monkeypatch):
    assert "AI · Local" in client.get("/").data.decode()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert "AI · OpenAI" in client.get("/").data.decode()
