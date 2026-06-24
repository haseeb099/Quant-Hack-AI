"""Tests for operator alert dispatch."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.operator import alerts


@pytest.fixture
def snapshot_red() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "RED",
        "reconciliation": {"status": "YELLOW", "issues": []},
        "risk_compliance": {"status": "GREEN", "issues": []},
        "mt5_checks": {
            "ready": False,
            "checks": [{"code": "ZMQ_DATA", "passed": False, "detail": "0 bars"}],
        },
        "mt5_log": {"status": "GREEN", "error_count": 0},
        "summary": {"mt5_position_count": 3, "engine_position_count": 3},
    }


def test_should_alert_respects_min_status(monkeypatch):
    monkeypatch.setenv("OPERATOR_ALERT_MIN_STATUS", "RED")
    assert alerts.should_alert("YELLOW") is False
    assert alerts.should_alert("RED") is True

    monkeypatch.setenv("OPERATOR_ALERT_MIN_STATUS", "YELLOW")
    assert alerts.should_alert("YELLOW") is True
    assert alerts.should_alert("GREEN") is False


def test_dispatch_writes_log_file(tmp_path, monkeypatch, snapshot_red):
    monkeypatch.setattr(alerts, "ALERT_LOG_PATH", tmp_path / "operator_alerts.log")
    monkeypatch.setattr("src.operator.snapshot_store.ALERT_DEDUPE_PATH", tmp_path / "dedupe.json")
    monkeypatch.setenv("OPERATOR_ALERT_MIN_STATUS", "RED")
    monkeypatch.setenv("OPERATOR_ALERT_LOG", "true")
    monkeypatch.setenv("OPERATOR_ALERT_LOGFIRE", "false")
    monkeypatch.setenv("OPERATOR_ALERT_DEDUPE_MINUTES", "0")

    result = alerts.dispatch_operator_alerts(snapshot_red)
    assert result["dispatched"] is True
    assert result["channels"]["log_file"] is True
    lines = (tmp_path / "operator_alerts.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status"] == "RED"
    assert "ZMQ_DATA" in record["message"]


def test_dispatch_dedupes_repeated_alerts(tmp_path, monkeypatch, snapshot_red):
    monkeypatch.setattr(alerts, "ALERT_LOG_PATH", tmp_path / "operator_alerts.log")
    monkeypatch.setattr("src.operator.snapshot_store.ALERT_DEDUPE_PATH", tmp_path / "dedupe.json")
    monkeypatch.setenv("OPERATOR_ALERT_MIN_STATUS", "RED")
    monkeypatch.setenv("OPERATOR_ALERT_LOG", "true")
    monkeypatch.setenv("OPERATOR_ALERT_LOGFIRE", "false")
    monkeypatch.setenv("OPERATOR_ALERT_DEDUPE_MINUTES", "60")

    first = alerts.dispatch_operator_alerts(snapshot_red)
    second = alerts.dispatch_operator_alerts(snapshot_red)
    assert first["dispatched"] is True
    assert second["dispatched"] is False
    assert second["reason"] == "deduped"
