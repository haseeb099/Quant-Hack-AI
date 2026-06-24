"""Tests for agents API vote flattening."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    state = default_state()
    state["last_cycle"] = {
        "symbols_processed": 1,
        "decisions": [],
        "agent_votes": [
            {
                "symbol": "EUR/USD",
                "votes": [
                    {"agent": "trend_surfer", "direction": "BUY", "confidence": 0.8},
                    {"agent": "mean_reversion", "direction": "HOLD", "confidence": 0.4},
                ],
            },
        ],
    }
    write_state(state, state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    app = create_app()
    assert app is not None
    return TestClient(app)


def test_last_cycle_flattens_nested_agent_votes(client: TestClient) -> None:
    r = client.get("/api/agents/last-cycle")
    assert r.status_code == 200
    votes = r.json()["agent_votes"]
    assert len(votes) == 2
    assert all(v["symbol"] == "EUR/USD" for v in votes)
    agents = {v["agent"] for v in votes}
    assert agents == {"trend_surfer", "mean_reversion"}


def test_last_cycle_preserves_flat_votes(client: TestClient, tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "runtime_state_flat.json"
    state = default_state()
    state["last_cycle"] = {
        "symbols_processed": 1,
        "decisions": [],
        "agent_votes": [
            {"agent": "momentum_pulse", "symbol": "XAU/USD", "direction": "SELL", "confidence": 0.7},
        ],
    }
    write_state(state, state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    app = create_app()
    client2 = TestClient(app)
    r = client2.get("/api/agents/last-cycle")
    votes = r.json()["agent_votes"]
    assert len(votes) == 1
    assert votes[0]["agent"] == "momentum_pulse"
    assert votes[0]["symbol"] == "XAU/USD"


def test_agents_health_endpoint(client: TestClient) -> None:
    r = client.get("/api/agents/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "agents" in body


def test_agents_audit_endpoint(client: TestClient) -> None:
    r = client.get("/api/agents/audit")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
    assert "recommendations" in body
