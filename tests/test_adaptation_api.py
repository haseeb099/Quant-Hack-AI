"""Adaptation API tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    plan_path = tmp_path / "adaptation_plan.json"
    db_path = tmp_path / "trade_memory.db"

    state = default_state()
    state["engine_running"] = True
    state["engine_paused"] = True
    state["mode"] = "simulate"
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, state_path)

    plan_path.write_text(json.dumps({
        "phase": "round1",
        "promoted": True,
        "old_weights": {"trend_surfer": 0.3},
        "new_weights": {"trend_surfer": 0.32},
        "walk_forward": {"oos_sharpe": 0.5},
    }), encoding="utf-8")

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.learning.adaptation_service.DEFAULT_PLAN_PATH", plan_path)

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_adaptation_status(client):
    r = client.get("/api/adaptation/status")
    assert r.status_code == 200
    body = r.json()
    assert body["can_run"] is True
    assert "current_weights" in body
    assert body["plan_exists"] is True
    assert body["plan"]["promoted"] is True


def test_adaptation_plan(client):
    r = client.get("/api/adaptation/plan")
    assert r.status_code == 200
    assert r.json()["exists"] is True


def test_adaptation_run_requires_confirm(client, monkeypatch):
    monkeypatch.setattr(
        "src.web.routes.adaptation.run_adaptation",
        lambda **kwargs: {"promoted": False, "phase": "round1", "trade_count": 0},
    )
    r = client.post("/api/adaptation/run", json={})
    assert r.status_code == 400

    r = client.post("/api/adaptation/run", json={"confirm": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_adaptation_run_blocked_when_live_active(tmp_path, monkeypatch):
    state_path = tmp_path / "live_state.json"
    state = default_state()
    state["mode"] = "live"
    state["engine_running"] = True
    state["engine_paused"] = False
    write_state(state, state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)

    app = create_app()
    client = TestClient(app)
    r = client.post("/api/adaptation/run", json={"confirm": True})
    assert r.status_code == 409
