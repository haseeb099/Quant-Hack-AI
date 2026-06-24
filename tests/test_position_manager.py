"""Tests for position manager M15 time stops and regime flip."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.risk.position_manager import PositionManager


def test_m15_bar_time_stop_uses_bar_count_not_cycles() -> None:
    pm = PositionManager({"time_stop_m15_bars": 4, "time_stop_min_r": 0.5, "regime_flip_enabled": False})
    entry_time = datetime.now(timezone.utc) - timedelta(minutes=75)
    pm.register_entry(
        ticket=1,
        symbol="EUR/USD",
        direction="BUY",
        entry_price=1.10,
        sl=1.09,
        volume=1.0,
        regime="ranging",
    )
    pm._state.meta[1].entry_time = entry_time.isoformat()

    current_bar = datetime.now(timezone.utc)
    actions = pm.evaluate(
        positions=[{
            "ticket": 1,
            "symbol": "EUR/USD",
            "type": "BUY",
            "price_open": 1.10,
            "price_current": 1.1005,
            "volume": 1.0,
        }],
        current_regimes={"EUR/USD": "ranging"},
        atr_by_symbol={"EUR/USD": 0.01},
        current_prices={"EUR/USD": 1.1005},
        m15_bar_times={"EUR/USD": current_bar},
    )
    assert any(a.action == "close" and "Time stop" in a.reason for a in actions)


def test_symmetric_regime_flip_for_short_in_trending() -> None:
    pm = PositionManager({"regime_flip_enabled": True})
    pm.register_entry(
        ticket=2,
        symbol="USD/JPY",
        direction="SELL",
        entry_price=150.0,
        sl=151.0,
        volume=1.0,
        regime="trending",
    )
    actions = pm.evaluate(
        positions=[{
            "ticket": 2,
            "symbol": "USD/JPY",
            "type": "SELL",
            "price_open": 150.0,
            "price_current": 149.8,
            "volume": 1.0,
        }],
        current_regimes={"USD/JPY": "ranging"},
        atr_by_symbol={"USD/JPY": 0.5},
        current_prices={"USD/JPY": 149.8},
    )
    assert any(a.action == "close" and "Regime flip" in a.reason for a in actions)


def test_profit_lock_closes_stagnant_winner() -> None:
    pm = PositionManager({
        "profit_lock_m15_bars": 8,
        "profit_lock_min_r": 0.7,
        "regime_flip_enabled": False,
        "enable_partial_takes": False,
        "enable_trailing": False,
    })
    entry_time = datetime.now(timezone.utc) - timedelta(minutes=8 * 15 + 5)
    pm.register_entry(
        ticket=3,
        symbol="GBP/USD",
        direction="SELL",
        entry_price=1.32,
        sl=1.324,
        volume=1.0,
        regime="trending",
    )
    pm._state.meta[3].entry_time = entry_time.isoformat()

    current_bar = datetime.now(timezone.utc)
    actions = pm.evaluate(
        positions=[{
            "ticket": 3,
            "symbol": "GBP/USD",
            "type": "SELL",
            "price_open": 1.32,
            "price_current": 1.317,
            "volume": 1.0,
        }],
        current_regimes={"GBP/USD": "trending"},
        atr_by_symbol={"GBP/USD": 0.002},
        current_prices={"GBP/USD": 1.317},
        m15_bar_times={"GBP/USD": current_bar},
    )
    assert any(a.action == "close" and "Profit lock" in a.reason for a in actions)
