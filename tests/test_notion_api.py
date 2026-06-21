"""Notion integration API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.integrations.notion_sync import NotionSync
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    sync_state = tmp_path / "notion_sync_state.json"
    state = default_state()
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, state_path)

    mock_sync = MagicMock(spec=NotionSync)
    mock_sync.enabled = True
    mock_sync.tasks_ds = "tasks-db-id"
    mock_sync.get_status.return_value = {
        "enabled": True,
        "api_key_set": True,
        "databases": {
            "trade_journal": True,
            "agent_performance": True,
            "risk_events": True,
            "tasks": True,
        },
        "sync_stats": {
            "trade_journal": {"success": 5, "failure": 0, "last_at": None, "last_error": None},
        },
    }
    mock_sync.query_tasks.return_value = [
        {"id": "1", "title": "Step 1 — Pre-trade gate", "status": "Done", "step": 1, "url": None},
        {"id": "2", "title": "Step 7 — Notion panel", "status": "In progress", "step": 7, "url": None},
    ]
    mock_sync.sync_implementation_step.return_value = True

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.integrations.notion_sync_tracker._STATE_PATH", sync_state)
    monkeypatch.setattr("src.web.routes.notion.get_notion_sync", lambda: mock_sync)
    monkeypatch.setattr("src.integrations.notion_sync.get_notion_sync", lambda: mock_sync)

    app = create_app()
    return TestClient(app)


def test_notion_status(client):
    r = client.get("/api/notion/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["databases"]["tasks"] is True


def test_notion_tasks(client):
    r = client.get("/api/notion/tasks")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["tasks"][0]["step"] == 1


def test_notion_sync_step(client):
    r = client.post(
        "/api/notion/sync/step",
        json={"step_label": "Step 7 — Notion panel", "status": "Done", "notes": "Shipped"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
