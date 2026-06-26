"""Tests for phase transition equity/peak/sharpe reset."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from src.engine.config import QuantAIConfig


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SENTIMENT_AGENT_ENABLED", "false")
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round1", auto_phase=False)
    return TradingEngine(config=config, simulation=True)


def test_rebuild_runtime_for_phase_updates_live_feed_symbols(engine) -> None:
    with patch.object(
        type(engine.config),
        "active_symbols",
        new_callable=PropertyMock,
        return_value=["EUR/USD", "GBP/USD"],
    ):
        engine._rebuild_runtime_for_phase()
    assert engine.live_feed.symbols == ["EUR/USD", "GBP/USD"]
    assert engine.drawdown_guard is not None
    assert engine.margin_monitor is not None


def test_maybe_refresh_phase_rebuilds_on_transition(engine) -> None:
    engine.config.current_phase = "round1"
    engine._initial_equity = 900_000.0
    engine._peak_equity = 950_000.0
    engine.sharpe_guard.record_equity(950_000.0)
    engine._symbol_cooldown_until["EUR/USD"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    new_config = MagicMock()
    new_config.current_phase = "round2"
    new_config.active_symbols = ["XAU/USD"]
    new_config.risk = engine.config.risk
    new_config.agents = engine.config.agents
    new_config.regime_boosts = engine.config.regime_boosts
    new_config.phase_rules = engine.config.phase_rules
    new_config.feature_update_seconds = engine.config.feature_update_seconds

    with patch("src.engine.trading_engine.resolve_phase", return_value="round2"), patch(
        "src.engine.trading_engine.QuantAIConfig.load",
        return_value=new_config,
    ), patch("src.engine.trading_engine.LayeredMemory"), patch(
        "src.engine.trading_engine.PeerMonitor",
    ), patch.object(
        engine.connector,
        "get_account_info",
        return_value={"status": "ok", "equity": 1_020_000.0},
    ):
        engine._maybe_refresh_phase()

    assert engine.config.current_phase == "round2"
    assert engine.live_feed.symbols == ["XAU/USD"]
    assert engine._initial_equity == 1_000_000.0
    assert engine._peak_equity == 1_020_000.0
    assert engine.sharpe_guard.snapshot_count() == 0
    assert engine._symbol_cooldown_until == {}
    assert engine._prev_dd_tier == "normal"


def test_round1_enables_partial_takes_and_breakeven(engine) -> None:
    from src.risk.position_manager import PositionManager

    pm = PositionManager(engine.config.phase_rules)
    assert pm.enable_partial_takes is True
    assert pm.enable_breakeven is True
    assert pm.partial_fraction == 0.33
    assert pm.breakeven_r == 0.75
    assert pm.enable_trailing is True
    assert pm.time_stop_bars == 12

    positions = [{
        "ticket": 100,
        "symbol": "EUR/USD",
        "type": "BUY",
        "volume": 1.0,
        "price_open": 1.10,
        "sl": 1.09,
        "price_current": 1.12,
    }]
    actions = pm.evaluate(
        positions,
        {"EUR/USD": "trending"},
        {"EUR/USD": 0.001},
        {"EUR/USD": 1.12},
        exit_prices={"EUR/USD": 1.12},
    )
    assert any(a.action == "partial_close" for a in actions)


def test_cycle_minutes_match_phase_rules(engine) -> None:
    assert engine.config.cycle_minutes() == 3
    assert engine._cycle_minutes == 3
    assert engine.state_publisher.cycle_minutes == 3


def test_publish_state_uses_phase_cycle_minutes(engine) -> None:
    from datetime import datetime, timezone

    engine._cycle_minutes = 3
    engine.state_publisher.cycle_minutes = 3
    cycle_start = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    engine._publish_state(cycle_start=cycle_start)
    assert engine._next_cycle_at == "2026-06-22T12:08:00+00:00"


def test_resolve_initial_equity_platform(monkeypatch) -> None:
    monkeypatch.setenv("ROUND_EQUITY_BASELINE", "platform")
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round2", auto_phase=False)
    eng = TradingEngine(config=config, simulation=True)
    assert eng._resolve_initial_equity(1_002_889.0) == 1_000_000.0


def test_resolve_initial_equity_session(monkeypatch) -> None:
    monkeypatch.setenv("ROUND_EQUITY_BASELINE", "session")
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round2", auto_phase=False)
    eng = TradingEngine(config=config, simulation=True)
    assert eng._resolve_initial_equity(1_002_889.0) == 1_002_889.0
