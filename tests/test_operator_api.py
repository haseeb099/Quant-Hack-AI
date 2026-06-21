"""Operator runbook and Northflank deploy API tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    state = default_state()
    state["engine_running"] = True
    state["mode"] = "simulate"
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_operator_runbook_endpoint(client):
    r = client.get("/api/operator/runbook")
    assert r.status_code == 200
    body = r.json()
    assert "phases" in body
    assert len(body["phases"]) == 4
    assert "preflight" in body
    assert body["preflight"]["total"] >= 1
    phase_ids = {p["id"] for p in body["phases"]}
    assert phase_ids == {"pre_launch", "launch", "during_round", "between_rounds"}


def test_operator_preflight_endpoint(client):
    r = client.get("/api/operator/preflight")
    assert r.status_code == 200
    body = r.json()
    assert "checks" in body
    assert "ready" in body
    codes = {c["code"] for c in body["checks"]}
    assert "DOCKERFILES" in codes
    assert "INSTRUMENTS" in codes


def test_northflank_deploy_endpoint(client):
    r = client.get("/api/deploy/northflank")
    assert r.status_code == 200
    body = r.json()
    assert body["platform"] == "northflank"
    assert len(body["services"]) == 2
    names = {s["name"] for s in body["services"]}
    assert names == {"quantai-engine", "quantai-dashboard"}
    assert "env_configured" in body
    assert "smoke_commands" in body
