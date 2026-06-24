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
def test_max_adverse_r_closes_immediately() -> None:
    pm = PositionManager({
        "max_adverse_r": -0.65,
        "regime_flip_enabled": False,
        "enable_partial_takes": False,
        "enable_trailing": False,
        "enable_breakeven": False,
    })
    pm.register_entry(
        ticket=10,
        symbol="USD/CAD",
        direction="BUY",
        entry_price=1.4000,
        sl=1.3980,
        volume=0.5,
        regime="trending",
    )
    # SL distance 0.0020; price 1.3987 => R = -0.65
    actions = pm.evaluate(
        positions=[{
            "ticket": 10,
            "symbol": "USD/CAD",
            "type": "BUY",
            "price_open": 1.4000,
            "price_current": 1.3986,
            "volume": 0.5,
            "sl": 1.3980,
        }],
        current_regimes={"USD/CAD": "trending"},
        atr_by_symbol={"USD/CAD": 0.001},
        current_prices={"USD/CAD": 1.3986},
    )
    assert any(a.action == "close" and "Max adverse cut" in a.reason for a in actions)


def test_never_green_exit_closes_stalled_loser() -> None:
    pm = PositionManager({
        "never_green_bars": 3,
        "never_green_peak_r": 0.05,
        "never_green_max_r": -0.15,
        "regime_flip_enabled": False,
        "enable_partial_takes": False,
        "enable_trailing": False,
        "enable_breakeven": False,
    })
    entry_time = datetime.now(timezone.utc) - timedelta(minutes=3 * 15 + 5)
    pm.register_entry(
        ticket=11,
        symbol="AUD/USD",
        direction="SELL",
        entry_price=0.6600,
        sl=0.6620,
        volume=0.5,
        regime="volatile",
    )
    pm._state.meta[11].entry_time = entry_time.isoformat()

    current_bar = datetime.now(timezone.utc)
    actions = pm.evaluate(
        positions=[{
            "ticket": 11,
            "symbol": "AUD/USD",
            "type": "SELL",
            "price_open": 0.6600,
            "price_current": 0.6604,
            "volume": 0.5,
            "sl": 0.6620,
        }],
        current_regimes={"AUD/USD": "volatile"},
        atr_by_symbol={"AUD/USD": 0.001},
        current_prices={"AUD/USD": 0.6604},
        m15_bar_times={"AUD/USD": current_bar},
    )
    assert any(a.action == "close" and "Never-green exit" in a.reason for a in actions)
