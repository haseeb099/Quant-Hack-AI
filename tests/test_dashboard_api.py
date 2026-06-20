"""Dashboard API integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.runtime_state import write_state, default_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    jsonl_path = tmp_path / "trades.jsonl"
    jsonl_path.write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00+00:00", "symbol": "XAU/USD", "direction": "BUY", "confidence": 0.8, "status": "decision", "regime": "trending", "session": "london", "agent_votes": []}) + "\n",
        encoding="utf-8",
    )
    write_state(default_state(), state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.routes.trades.JSONL_PATH", jsonl_path)

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "phase" in data
    assert "connected" in data


def test_account(client):
    r = client.get("/api/account")
    assert r.status_code == 200
    assert r.json()["equity"] == 1_000_000


def test_positions(client):
    r = client.get("/api/positions")
    assert r.status_code == 200
    assert "positions" in r.json()


def test_trades_list(client):
    r = client.get("/api/trades")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert len(body["trades"]) >= 1


def test_trades_detail(client):
    r = client.get("/api/trades/0")
    assert r.status_code == 200
    assert r.json()["symbol"] == "XAU/USD"


def test_agents(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert len(r.json()["agents"]) == 4


def test_risk(client):
    r = client.get("/api/risk")
    assert r.status_code == 200
    assert "dd_tier" in r.json()


def test_instruments(client):
    r = client.get("/api/instruments")
    assert r.status_code == 200
    assert r.json()["count"] == 15


def test_equity_curve(client):
    r = client.get("/api/equity-curve")
    assert r.status_code == 200
    assert "history" in r.json()
