"""Tests for SharpeGuard threshold tuning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.risk.sharpe_guard import SharpeGuard, PNL_THRESHOLD


def test_pnl_threshold_default():
    assert PNL_THRESHOLD == -0.005


def test_round2_phase_threshold():
    guard = SharpeGuard()
    guard.set_phase("round2")
    assert guard.pnl_threshold == -0.008


def test_reset_round_clears_snapshots():
    guard = SharpeGuard(snapshot_interval_minutes=0)
    guard.record_equity(1_000_000)
    guard.record_equity(999_000)
    assert guard.snapshot_count() == 2
    guard.reset_round(995_000)
    assert guard.snapshot_count() == 0
    assert guard._peak_equity == 995_000


def test_requires_consecutive_bad_snapshots_without_drawdown():
    guard = SharpeGuard(snapshot_interval_minutes=0)
    guard.record_equity(1_000_000)
    guard.record_equity(999_000)
    guard.record_equity(998_000)
    positions = [{
        "ticket": 42,
        "symbol": "EUR/USD",
        "type": "BUY",
        "volume": 1.0,
        "price_open": 1.10,
        "profit": -100.0,
    }]
    guard._last_snapshot = datetime.now(timezone.utc) - timedelta(minutes=10)
    tickets = guard.evaluate(positions, 998_000, lambda _p: -0.004)
    assert 42 not in tickets

    guard.record_equity(997_000)
    tickets = guard.evaluate(positions, 997_000, lambda _p: -0.006)
    assert 42 in tickets
