"""Tests for drawdown tier thresholds with distinct warning/critical bands."""

from __future__ import annotations

from src.risk.drawdown_guard import DrawdownGuard


def _guard() -> DrawdownGuard:
    return DrawdownGuard({
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
    })


def test_12pct_drawdown_is_warning_tier() -> None:
    guard = _guard()
    guard.reset(1_000_000)
    state = guard.update(880_000)
    assert state.tier == "warning"


def test_13pct_drawdown_stays_warning_not_critical() -> None:
    guard = _guard()
    guard.reset(1_000_000)
    state = guard.update(870_000)
    assert state.tier == "warning"


def test_14pct_drawdown_is_critical_tier() -> None:
    guard = _guard()
    guard.reset(1_000_000)
    state = guard.update(860_000)
    assert state.tier == "critical"


def test_15pct_drawdown_is_emergency_tier() -> None:
    guard = _guard()
    guard.reset(1_000_000)
    state = guard.update(850_000)
    assert state.tier == "emergency"
    assert not state.allow_new_trades


def test_peak_reset_micro_account_bound() -> None:
    guard = _guard()
    guard.peak_equity = 5000
    equity = 1.0
    bound = max(equity * 2, 1000)
    assert guard.peak_equity > bound
    guard.reset(equity)
    assert guard.peak_equity == equity

