"""Tests for OPEN fill reconciliation and orphan prevention."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.bridges.zeromq_connector import FILL_RECOVERY_POLL_SEC, VOLUME_EPS
from src.engine.trading_engine import TradingEngine


class _StubConnector:
    bridge_type = "zmq"

    def __init__(self, positions: list[dict] | None = None) -> None:
        self._positions = list(positions or [])
        self.last_error = ""

    @property
    def is_connected(self) -> bool:
        return True

    def get_positions(self) -> list[dict]:
        return list(self._positions)

    def get_account_info(self) -> dict:
        return {"equity": 100_000.0, "gross_exposure": 0}


def _engine_stub(connector: _StubConnector) -> TradingEngine:
    engine = TradingEngine.__new__(TradingEngine)
    engine.connector = connector
    engine.simulation = False
    engine._fill_undershoot_block = False
    engine._fill_overshoot_block = False
    return engine


def test_open_poll_waits_before_declaring_zero_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _StubConnector()
    engine = _engine_stub(connector)
    polls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        polls.append(seconds)
        if len(polls) == 2:
            connector._positions = [{"ticket": 42, "symbol": "EURUSD", "type": "BUY", "volume": 0.1}]

    monkeypatch.setattr(time, "sleep", fake_sleep)

    after = engine._log_position_reconcile(
        42,
        0.1,
        "OPEN",
        {"status": "ok"},
        symbol="EUR/USD",
        direction="BUY",
        baseline_volume=0.0,
    )

    assert len(polls) >= 2
    assert polls[0] == FILL_RECOVERY_POLL_SEC
    assert after > VOLUME_EPS


def test_zero_volume_open_does_not_register_open_trades(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _StubConnector()
    engine = _engine_stub(connector)
    engine._open_trades = {}
    engine._sync_open_trades_from_mt5 = MagicMock()
    monkeypatch.setattr(time, "sleep", lambda _: None)

    after = engine._log_position_reconcile(
        99,
        0.2,
        "OPEN",
        {"status": "ok"},
        symbol="GBP/USD",
        direction="SELL",
        baseline_volume=0.0,
    )

    assert after <= VOLUME_EPS
    assert 99 not in engine._open_trades


def test_partial_fill_syncs_ledger_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _StubConnector(
        [{"ticket": 7, "symbol": "EURUSD", "type": "BUY", "volume": 0.05, "time": 1}],
    )
    engine = _engine_stub(connector)
    monkeypatch.setenv("PARTIAL_FILL_ABORT", "false")
    monkeypatch.setenv("PARTIAL_FILL_MIN_RATIO", "0")

    after = engine._log_position_reconcile(
        7,
        0.1,
        "OPEN",
        {"status": "ok", "volume": 0.05},
        symbol="EUR/USD",
        direction="BUY",
    )

    assert after == pytest.approx(0.05)
    assert after < 0.1 - VOLUME_EPS
