"""Demo walkthrough and technology prize API tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.demo.walkthrough import build_demo_walkthrough
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    state = default_state()
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_demo_walkthrough_endpoint(client):
    r = client.get("/api/demo/walkthrough")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "QuantAI Demo Walkthrough"
    assert len(body["steps"]) == 6
    assert body["duration_sec"] >= 300
    assert body["summary"]["total"] == 6


def test_technology_prize_endpoint(client):
    r = client.get("/api/prize/technology-checklist")
    assert r.status_code == 200
    body = r.json()
    assert "checks" in body
    assert "ready" in body
    codes = {c["code"] for c in body["checks"]}
    assert "ANTHROPIC" in codes
    assert "LOGFIRE" in codes
    assert "NORTHFLANK_DASHBOARD" in codes
    assert body["summary"]["pass"] >= 5


def test_walkthrough_steps_have_narration():
    data = build_demo_walkthrough()
    for step in data["steps"]:
        assert step["narration"]
        assert step["order"] >= 1
        assert step["status"] in ("pass", "warn", "fail", "manual")
