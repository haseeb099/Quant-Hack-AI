"""Launch readiness API tests."""

from __future__ import annotations

import json
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


def test_launch_readiness_endpoint(client):
    r = client.get("/api/competition/launch-readiness")
    assert r.status_code == 200
    body = r.json()
    assert "ready" in body
    assert "checks" in body
    assert isinstance(body["checks"], list)
    assert body["summary"]["pass"] >= 1
    codes = {c["code"] for c in body["checks"]}
    assert "ENGINE_RUNNING" in codes
    assert "LOGFIRE" in codes
    assert "competition_launch_at" in body


def test_launch_readiness_fails_when_engine_stopped(client, tmp_path, monkeypatch):
    state = default_state()
    state["engine_running"] = False
    state_path = tmp_path / "stopped.json"
    write_state(state, state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)

    r = client.get("/api/competition/launch-readiness")
    body = r.json()
    assert body["ready"] is False
    engine = next(c for c in body["checks"] if c["code"] == "ENGINE_RUNNING")
    assert engine["status"] == "fail"
