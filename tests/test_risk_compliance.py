"""Tests for risk compliance checks."""

from __future__ import annotations

from src.operator.risk_compliance import check_risk_compliance
from src.web.runtime_state import default_state


def _state(**overrides) -> dict:
    state = default_state()
    state.update(overrides)
    return state


def test_risk_compliance_green_on_normal_state() -> None:
    state = _state(
        risk={
            "dd_tier": "normal",
            "drawdown_pct": 0.02,
            "effective_leverage": 5.0,
            "concentration_pct": 0.15,
            "margin_state": {"margin_level_pct": 800, "action": "normal"},
        },
        account={"equity": 100_000, "balance": 100_500},
    )
    result = check_risk_compliance(state=state)
    assert result["status"] == "GREEN"
    assert any(i["code"] == "DRAWDOWN_HEADROOM" for i in result["issues"])


def test_risk_compliance_red_on_stop_out_margin() -> None:
    state = _state(
        risk={
            "dd_tier": "warning",
            "drawdown_pct": 0.11,
            "effective_leverage": 10.0,
            "concentration_pct": 0.2,
            "margin_state": {"margin_level_pct": 25, "action": "EMERGENCY"},
        },
        account={"equity": 90_000, "balance": 100_000},
    )
    result = check_risk_compliance(state=state)
    margin_issue = next(i for i in result["issues"] if i["code"] == "MARGIN_LEVEL")
    assert margin_issue["passed"] is False
    assert result["status"] == "RED"


def test_risk_compliance_flags_upcoming_events() -> None:
    from datetime import datetime, timedelta, timezone

    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state = _state()
    result = check_risk_compliance(
        state=state,
        calendar_events=[{"impact": "high", "time": soon, "title": "NFP"}],
    )
    assert result["upcoming_events"]
    event_issue = next(i for i in result["issues"] if i["code"] == "EVENT_GATE")
    assert "1 high-impact" in event_issue["detail"]
