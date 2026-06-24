"""Tests for Command Center fix plan — peak reset, agents, win_rate, formatting."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory
from src.operator.formatting import format_launch_summary
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.pre_trade_gate import PreTradeRiskGate, TradeCheckRequest
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


def _drawdown_config() -> dict:
    return {
        "normal_max": 0.05,
        "elevated_max": 0.10,
        "warning_max": 0.12,
        "critical_max": 0.14,
        "emergency_close": 0.15,
        "size_multipliers": {
            "normal": 1.0,
            "elevated": 0.75,
            "warning": 0.5,
            "critical": 0.25,
            "emergency": 0.0,
        },
    }


def test_peak_reset_when_stale_million_dollar_peak_on_one_dollar_equity() -> None:
    guard = DrawdownGuard(_drawdown_config())
    guard.peak_equity = 1_000_000
    equity = 1.0

    ratio = guard.peak_equity / equity
    implied_dd = (guard.peak_equity - equity) / guard.peak_equity
    assert ratio > 10
    assert implied_dd >= 0.50

    guard.reset(equity)
    state = guard.update(equity)
    assert guard.peak_equity == equity
    assert state.tier == "normal"


def test_pre_trade_gate_resets_inflated_peak_instead_of_reconstructing() -> None:
    gate = PreTradeRiskGate(QuantAIConfig.load())
    gate.drawdown_guard.peak_equity = 1_000_000

    state = default_state()
    state["mode"] = "simulate"
    state["account_profile"] = "micro"
    state["account"]["equity"] = 1.0
    state["account"]["balance"] = 1.0
    state["risk"]["drawdown_pct"] = 0.999999
    state["risk"]["dd_tier"] = "emergency"

    gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert gate.drawdown_guard.peak_equity == 1.0


def test_agent_performance_returns_null_win_rate_at_zero_samples(tmp_path) -> None:
    memory = LayeredMemory(db_path=tmp_path / "trade_memory.db")
    perf = memory.agent_performance("trend_surfer")
    assert perf["sample_size"] == 0
    assert perf["win_rate"] is None


def test_format_launch_summary() -> None:
    assert format_launch_summary({"pass": 3, "warn": 1, "fail": 0, "skip": 2}) == (
        "3 pass · 1 warn · 0 fail · 2 skip"
    )
    assert format_launch_summary(None) == "0 pass · 0 warn · 0 fail · 0 skip"


@pytest.fixture
def agents_client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    jsonl_path = tmp_path / "trades.jsonl"
    jsonl_path.write_text("", encoding="utf-8")
    write_state(default_state(), state_path)

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.routes.trades.JSONL_PATH", jsonl_path)

    app = create_app()
    return TestClient(app)


def test_agents_api_returns_six_agents(agents_client: TestClient) -> None:
    r = agents_client.get("/api/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert len(agents) == 6
    names = {a["agent"] for a in agents}
    assert "sentiment_agent" in names
    assert "ml_signal" in names
