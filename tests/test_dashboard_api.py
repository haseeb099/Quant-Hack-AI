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


def test_competition_score(client):
    r = client.get("/api/competition-score")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert len(body["components"]) == 4


def test_engine_health(client):
    r = client.get("/api/health/engine")
    assert r.status_code == 200
    body = r.json()
    assert "engine_running" in body
    assert "data_source" in body


def test_integrations(client):
    r = client.get("/api/integrations")
    assert r.status_code == 200
    body = r.json()
    assert "notion" in body
    assert "logfire" in body


def test_status_data_source(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "data_source" in r.json()


def test_trades_status_filter(client):
    r = client.get("/api/trades?status=decision")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_positions_totals(client):
    r = client.get("/api/positions")
    assert r.status_code == 200
    body = r.json()
    assert "total_exposure" in body
    assert "total_unrealized_pnl" in body


def test_agent_attribution(client):
    r = client.get("/api/agents/attribution")
    assert r.status_code == 200
    assert "attribution" in r.json()


def test_check_trade_allowed(client):
    r = client.get("/api/risk/check-trade?symbol=EUR/USD&direction=BUY&volume=0.01")
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is True
    assert "blockers" in body
    assert "projected" in body


def test_check_trade_invalid_symbol(client):
    r = client.get("/api/risk/check-trade?symbol=NOTREAL/USD&direction=BUY&volume=0.01")
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is False
    assert any(b["code"] == "INVALID_SYMBOL" for b in body["blockers"])
