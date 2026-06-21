"""Notion A–Z sync tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.integrations.notion_az_content import AZ_SECTIONS, IMPLEMENTATION_STEPS
from src.integrations.notion_az_sync import sync_az_to_notion, upsert_implementation_step
from src.web.app import create_app


def test_az_content_complete():
    assert len(IMPLEMENTATION_STEPS) == 10
    assert len(AZ_SECTIONS) == 26
    letters = {s["letter"] for s in AZ_SECTIONS}
    assert letters == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_sync_az_disabled():
    mock_sync = MagicMock()
    mock_sync.enabled = False
    result = sync_az_to_notion(mock_sync)
    assert "error" in result
    assert result.get("ok") is not True


@patch("src.integrations.notion_az_sync.record_sync_result")
def test_upsert_creates_when_missing(mock_record):
    mock_sync = MagicMock()
    mock_sync.enabled = True
    mock_sync.tasks_ds = "db-id"
    mock_sync._client = MagicMock()
    mock_sync._title = lambda t: {"title": [{"text": {"content": t}}]}
    mock_sync._select = lambda s: {"select": {"name": s}}
    mock_sync._rich_text = lambda t: {"rich_text": [{"text": {"content": t}}]}
    mock_sync.query_tasks.return_value = []

    action = upsert_implementation_step(mock_sync, "Step 1 — Test", notes="ok", step_num="1")
    assert action == "created"
    mock_sync._client.pages.create.assert_called_once()


@pytest.fixture
def client(tmp_path, monkeypatch):
    mock_sync = MagicMock()
    mock_sync.enabled = True
    mock_sync.tasks_ds = "tasks-db"
    mock_sync.get_status.return_value = {"enabled": True, "databases": {"tasks": True}}
    mock_sync.query_tasks.return_value = []

    monkeypatch.setattr("src.web.routes.notion.get_notion_sync", lambda: mock_sync)
    monkeypatch.setattr(
        "src.web.routes.notion.sync_az_to_notion",
        lambda sync, **kw: {"ok": True, "steps": [{"step": "1", "action": "updated"}]},
    )

    app = create_app()
    return TestClient(app)


def test_notion_sync_az_endpoint(client):
    r = client.post("/api/notion/sync/az")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "steps" in body
