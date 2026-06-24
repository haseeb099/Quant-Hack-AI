"""Tests for unified pre-trade risk gate."""

from __future__ import annotations

import pytest

from src.risk.pre_trade_gate import PreTradeRiskGate, TradeCheckRequest
from src.web.runtime_state import default_state


@pytest.fixture
def gate() -> PreTradeRiskGate:
    return PreTradeRiskGate()


def _base_state() -> dict:
    state = default_state()
    state["mode"] = "simulate"
    state["engine_running"] = True
    state["engine_paused"] = False
    return state


def _live_state() -> dict:
    state = _base_state()
    state["mode"] = "live"
    state["mt5_connected"] = True
    state["account"] = {
        "equity": 50_000,
        "balance": 50_000,
        "margin": 0,
        "free_margin": 50_000,
        "gross_exposure": 0,
        "status": "ok",
    }
    return state


def test_allows_clean_simulate_trade(gate: PreTradeRiskGate) -> None:
    result = gate.evaluate_from_state(
        _base_state(),
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is True
    assert result.blockers == []


def test_blocks_invalid_symbol(gate: PreTradeRiskGate) -> None:
    result = gate.evaluate_from_state(
        _base_state(),
        TradeCheckRequest(symbol="FAKE/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "INVALID_SYMBOL" for b in result.blockers)


def test_blocks_engine_paused(gate: PreTradeRiskGate) -> None:
    state = _base_state()
    state["engine_paused"] = True
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="XAU/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "ENGINE_PAUSED" for b in result.blockers)


def test_blocks_duplicate_position(gate: PreTradeRiskGate) -> None:
    state = _base_state()
    state["positions"] = [
        {"symbol": "XAU/USD", "type": "BUY", "volume": 0.1, "price_open": 2350},
    ]
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="XAU/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "DUPLICATE_POSITION" for b in result.blockers)


def test_blocks_critical_drawdown_tier(gate: PreTradeRiskGate) -> None:
    state = _base_state()
    state["risk"]["dd_tier"] = "critical"
    state["risk"]["drawdown_pct"] = 0.13
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "DRAWDOWN_TIER" for b in result.blockers)


def test_blocks_stale_ticks_in_live_mode(gate: PreTradeRiskGate) -> None:
    state = _live_state()
    state["market"]["last_tick_age_ms"] = 12_000
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "STALE_TICKS" for b in result.blockers)


def test_blocks_missing_ticks_in_live_mode(gate: PreTradeRiskGate) -> None:
    state = _live_state()
    state["market"] = {"last_tick_at": None, "last_tick_age_ms": None}
    state["instruments"] = {}
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "STALE_TICKS" for b in result.blockers)


def test_blocks_live_when_account_equity_unavailable(gate: PreTradeRiskGate) -> None:
    state = _live_state()
    state["account"] = {"equity": None, "margin": 0, "gross_exposure": 0}
    state["market"]["last_tick_age_ms"] = 100
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is False
    assert any(b.code == "BRIDGE_OFFLINE" for b in result.blockers)


def test_blocks_excessive_leverage(gate: PreTradeRiskGate) -> None:
    state = _base_state()
    state["account"]["equity"] = 10_000
    state["account"]["gross_exposure"] = 150_000
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="BTC/USD", direction="BUY", volume=1.0, price=95_000),
    )
    assert result.allowed is False
    assert any(b.code == "LEVERAGE" for b in result.blockers)


def test_result_serializes_to_dict(gate: PreTradeRiskGate) -> None:
    result = gate.evaluate_from_state(
        _base_state(),
        TradeCheckRequest(symbol="EUR/USD", direction="SELL", volume=0.02),
    )
    payload = result.to_dict()
    assert "allowed" in payload
    assert "blockers" in payload
    assert "projected" in payload


def test_blocks_projected_concentration(gate: PreTradeRiskGate) -> None:
    state = _base_state()
    state["account"]["equity"] = 10_000
    state["account"]["largest_position_pct"] = 0.25
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(symbol="BTC/USD", direction="BUY", volume=0.05, price=95_000),
    )
    assert result.allowed is False
    assert any(b.code == "CONCENTRATION_PROJECTED" for b in result.blockers)
    assert result.projected["projected_concentration_pct"] > 0.40


def test_projected_concentration_in_clean_trade(gate: PreTradeRiskGate) -> None:
    result = gate.evaluate_from_state(
        _base_state(),
        TradeCheckRequest(symbol="EUR/USD", direction="BUY", volume=0.01),
    )
    assert result.allowed is True
    assert "projected_concentration_pct" in result.projected


def test_blocks_wide_spread_in_live_mode(gate: PreTradeRiskGate) -> None:
    state = _live_state()
    state["instruments"]["EUR/USD"] = {
        "bid": 1.1000,
        "ask": 1.1020,
        "tick_age_ms": 100,
    }
    state["market"]["last_tick_age_ms"] = 100
    result = gate.evaluate_from_state(
        state,
        TradeCheckRequest(
            symbol="EUR/USD",
            direction="BUY",
            volume=0.01,
            atr_14=0.0010,
        ),
    )
    assert result.allowed is False
    assert any(b.code == "WIDE_SPREAD" for b in result.blockers)
