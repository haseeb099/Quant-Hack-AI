"""Copilot API integration tests — grounded analysis, no execution."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


def _copilot_state() -> dict:
    state = default_state()
    state["engine_running"] = True
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    state["instruments"] = {
        "XAU/USD": {
            "mid": 2350.5,
            "bid": 2350.4,
            "ask": 2350.6,
            "tick_age_ms": 120,
            "updated_at": state["timestamp"],
        },
    }
    return state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    write_state(_copilot_state(), state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_analyze_symbol_returns_citations(client):
    r = client.post(
        "/api/copilot/analyze-symbol?symbol=XAU/USD&use_llm=false",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "XAU/USD"
    assert body["verdict"] in ("ALLOW", "WAIT", "BLOCK", "REFUSE")
    assert body["provider"] == "template"
    assert len(body["data_citations"]) >= 3
    sources = {c["source"] for c in body["data_citations"]}
    assert "runtime_state.account" in sources
    assert "pre_trade_gate" in sources


def test_analyze_symbol_refuses_invalid_symbol(client):
    r = client.post(
        "/api/copilot/analyze-symbol?symbol=FAKE/USD&use_llm=false",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "REFUSE"
    assert body["refused"] is True
    assert "not a competition instrument" in body["summary"].lower()


def test_analyze_symbol_refuses_stale_live_ticks(client, tmp_path, monkeypatch):
    state = _copilot_state()
    state["mode"] = "live"
    state["mt5_connected"] = True
    state["instruments"]["XAU/USD"]["tick_age_ms"] = 9000
    state_path = tmp_path / "stale_live.json"
    write_state(state, state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)

    r = client.post(
        "/api/copilot/analyze-symbol?symbol=XAU/USD&use_llm=false",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "REFUSE"
    assert "stale" in body["summary"].lower()


def test_chat_sse_streams_analysis(client):
    with client.stream(
        "POST",
        "/api/copilot/chat",
        json={"message": "What is the setup on Gold?"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        assert any(e.get("type") == "start" for e in events)
        assert any(e.get("type") == "citations" for e in events)
        assert any(e.get("type") == "done" for e in events)
        done = next(e for e in events if e.get("type") == "done")
        assert done["analysis"] is not None
        assert done["analysis"]["symbol"] == "XAU/USD"


def test_chat_without_symbol_returns_account_summary(client):
    with client.stream(
        "POST",
        "/api/copilot/chat",
        json={"message": "How is my account?"},
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        text_events = [e for e in events if e.get("type") == "text"]
        assert text_events
        assert "equity" in text_events[0]["content"].lower()
        done = next(e for e in events if e.get("type") == "done")
        assert done["analysis"] is None
