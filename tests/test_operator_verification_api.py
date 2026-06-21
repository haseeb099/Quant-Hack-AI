"""Competition-day verification API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.operator.verification import competition_session_phase
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    verify_path = tmp_path / "operator_verification.json"
    state = default_state()
    state["engine_running"] = True
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)
    monkeypatch.setattr("src.operator.verification_store._STATE_PATH", verify_path)
    monkeypatch.setattr("src.operator.runbook.read_verification_state", lambda: {
        "checks": [{"code": "PYTEST", "passed": True, "detail": "5 passed"}],
    })

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_verification_status_endpoint(client):
    r = client.get("/api/operator/verification")
    assert r.status_code == 200
    body = r.json()
    assert "session" in body
    assert "has_run" in body
    assert body["session"]["phase"] in {
        "pre_session", "pre_launch", "during_round", "between_rounds", "pre_competition",
    }


def test_verification_run_requires_confirm(client):
    r = client.post("/api/operator/verification/run", json={"confirm": False})
    assert r.status_code == 400


def test_verification_run_endpoint(client):
    mock_result = {
        "ready": True,
        "passed": 5,
        "total": 5,
        "mode": "quick",
        "checks": [{"code": "PYTEST", "label": "Pytest", "passed": True, "detail": "ok"}],
        "session": competition_session_phase(),
        "preflight": {"ready": True, "passed": 8, "total": 8},
        "launch_readiness": True,
    }
    with patch("src.web.routes.operator.run_verification", return_value=mock_result):
        r = client.post("/api/operator/verification/run", json={"confirm": True, "quick": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ready"] is True
    assert len(body["checks"]) == 1


def test_competition_session_phase_labels():
    session = competition_session_phase()
    assert "label" in session
    assert "seconds_to_launch" in session
