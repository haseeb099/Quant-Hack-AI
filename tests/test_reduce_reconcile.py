"""Tests for engine partial-reduce reconcile behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.engine.trading_engine import TradingEngine


def _engine_stub() -> TradingEngine:
    engine = TradingEngine.__new__(TradingEngine)
    engine.connector = MagicMock()
    engine.position_manager = MagicMock()
    engine.trade_logger = MagicMock()
    engine.trade_logger.jsonl_path = "logs/trades.jsonl"
    engine._open_trades = {}
    engine._finalized_tickets = set()
    engine.simulation = False
    return engine


def test_reduce_confirmed_without_escalation(monkeypatch) -> None:
    engine = _engine_stub()
    calls = {"n": 0}

    def fake_volume(ticket: int) -> float:
        calls["n"] += 1
        return 1.0 if calls["n"] == 1 else 0.5

    engine._position_volume = fake_volume  # type: ignore[method-assign]
    engine.connector.reduce_position.return_value = {
        "status": "ok",
        "remaining_volume": 0.5,
    }
    engine._log_position_reconcile = MagicMock(return_value=0.5)  # type: ignore[method-assign]
    engine._get_symbol_info = MagicMock(return_value={"volume_step": 0.01, "volume_min": 0.01})  # type: ignore[method-assign]

    result = engine._reduce_with_reconcile(42, 0.5, "EUR/USD")

    assert result["confirmed"] is True
    assert result.get("escalated_to_full") is False
    engine.connector.close_position.assert_not_called()


def test_reduce_escalates_when_volume_unchanged(monkeypatch) -> None:
    engine = _engine_stub()
    engine._position_volume = MagicMock(return_value=1.0)  # type: ignore[method-assign]
    engine.connector.reduce_position.return_value = {"status": "ok", "remaining_volume": 1.0}
    engine.connector.close_position.return_value = {
        "status": "ok",
        "remaining_volume": 0.0,
    }
    engine._log_position_reconcile = MagicMock(return_value=1.0)  # type: ignore[method-assign]
    engine._get_symbol_info = MagicMock(return_value={"volume_step": 0.01, "volume_min": 0.01})  # type: ignore[method-assign]
    engine._close_position_confirmed = MagicMock(return_value=True)  # type: ignore[method-assign]

    monkeypatch.setattr("src.engine.trading_engine.time.sleep", lambda *_: None)

    result = engine._reduce_with_reconcile(99, 0.5, "EUR/USD")

    assert result.get("escalated_to_full") is True
    engine.connector.close_position.assert_called_once_with(99)


def test_open_partial_fill_does_not_block() -> None:
    engine = _engine_stub()
    engine._fill_undershoot_block = False
    engine._position_volume = MagicMock(return_value=1.0)  # type: ignore[method-assign]

    after = engine._log_position_reconcile(10, 4.93, "OPEN", {"status": "ok"})

    assert after == 1.0
    assert engine._fill_undershoot_block is False


def test_open_zero_fill_sets_block_flag() -> None:
    engine = _engine_stub()
    engine._fill_undershoot_block = False
    engine._position_volume = MagicMock(return_value=0.0)  # type: ignore[method-assign]

    after = engine._log_position_reconcile(10, 4.93, "OPEN", {"status": "ok"})

    assert after == 0.0
    assert engine._fill_undershoot_block is True


def test_open_reconcile_polls_before_zero_fill(monkeypatch) -> None:
    engine = _engine_stub()
    calls = {"n": 0}

    def fake_volume(ticket: int) -> float:
        calls["n"] += 1
        return 1.0 if calls["n"] >= 2 else 0.0

    engine._position_volume = fake_volume  # type: ignore[method-assign]
    engine._fill_undershoot_block = False
    monkeypatch.setattr("src.engine.trading_engine.time.sleep", lambda *_: None)

    after = engine._log_position_reconcile(
        10,
        4.93,
        "OPEN",
        {"status": "ok"},
        symbol="EUR/USD",
        direction="BUY",
    )

    assert after == 1.0
    assert engine._fill_undershoot_block is False
