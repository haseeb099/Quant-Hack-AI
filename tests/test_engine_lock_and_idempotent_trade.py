"""Tests for live engine singleton lock and idempotent ZMQ trades."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.bridges.zeromq_connector import ZeroMQConnector
from src.engine.engine_lock import EngineProcessLock


def test_engine_lock_blocks_second_live_process(tmp_path) -> None:
    lock_path = tmp_path / "engine.lock"
    first = EngineProcessLock(lock_path)
    first.acquire(mode="live")

    second = EngineProcessLock(lock_path)
    with pytest.raises(RuntimeError, match="already running"):
        second.acquire(mode="live")

    first.release()


def test_engine_lock_ignored_for_simulate(tmp_path) -> None:
    lock_path = tmp_path / "engine.lock"
    lock = EngineProcessLock(lock_path)
    lock.acquire(mode="simulate")
    assert not lock_path.exists()


def test_send_trade_does_not_resend_when_mt5_shows_fill() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._connected = True
    conn._bridge_responding = True
    calls = {"n": 0}

    def flaky_send(command: dict, *, drain_stale: bool = True) -> dict:
        calls["n"] += 1
        return {"status": "error", "message": "Request timed out", "action": "TRADE"}

    conn._send_command = flaky_send  # type: ignore[method-assign]
    conn.get_symbol_info = MagicMock(  # type: ignore[method-assign]
        return_value={"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0},
    )
    conn._mt5_volume_for_symbol_direction = MagicMock(  # type: ignore[method-assign]
        side_effect=[0.0, 5.73, 5.73, 5.73, 5.73, 5.73],
    )
    conn._recover_open_trade_result = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            None,
            {
                "status": "ok",
                "action": "TRADE",
                "symbol": "AUD/USD",
                "type": "SELL",
                "volume": 5.73,
                "ticket": 42818,
                "price": 0.70005,
                "slippage": 0.70005,
                "fill_rate": 1.0,
                "latency_ms": 0,
                "recovered": True,
            },
        ],
    )
    conn._poll_recovered_open_trade = MagicMock(  # type: ignore[method-assign]
        return_value={
            "status": "ok",
            "action": "TRADE",
            "symbol": "AUD/USD",
            "type": "SELL",
            "volume": 5.73,
            "ticket": 42818,
            "price": 0.70005,
            "slippage": 0.70005,
            "fill_rate": 1.0,
            "latency_ms": 0,
            "recovered": True,
        },
    )

    with patch("src.bridges.zeromq_connector.time.sleep"):
        result = conn.send_trade("AUD/USD", "SELL", 5.73)

    assert result["status"] == "ok"
    assert result.get("recovered") is True
    assert calls["n"] == 1


def test_trade_command_skips_stale_drain() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._push_socket = MagicMock()
    conn._pull_socket = MagicMock()
    drained = {"n": 0}

    def fake_drain(max_messages: int = 8) -> None:
        drained["n"] += 1

    conn._drain_pull_socket = fake_drain  # type: ignore[method-assign]

    import zmq

    conn._pull_socket.recv_string.side_effect = zmq.Again()

    conn._send_command({"action": "TRADE", "type": "SELL", "symbol": "AUD/USD", "volume": 1.0})
    assert drained["n"] == 0

    conn._send_command({"action": "ACCOUNT"})
    assert drained["n"] == 1


def test_get_positions_snapshot_fail_closed_when_unavailable() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._positions_from_mt5 = MagicMock(return_value=None)  # type: ignore[method-assign]
    conn._send_command = MagicMock(  # type: ignore[method-assign]
        return_value={"status": "error", "message": "timeout"},
    )

    snap = conn.get_positions_snapshot()
    assert snap.trusted is False
    assert snap.positions == []


def test_get_positions_snapshot_prefers_mt5() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    mt5_positions = [{"ticket": 1, "symbol": "AUD/USD", "volume": 5.73, "type": "SELL"}]
    conn._positions_from_mt5 = MagicMock(return_value=mt5_positions)  # type: ignore[method-assign]

    snap = conn.get_positions_snapshot()
    assert snap.trusted is True
    assert snap.positions == mt5_positions


def test_close_does_not_resend_when_mt5_shows_position_gone() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._connected = True
    conn._bridge_responding = True
    calls = {"n": 0}

    def flaky_send(command: dict, *, drain_stale: bool = True) -> dict:
        calls["n"] += 1
        return {"status": "error", "message": "Request timed out", "action": "TRADE"}

    conn._send_command = flaky_send  # type: ignore[method-assign]
    conn._mt5_volume_for_ticket = MagicMock(side_effect=[22.92, 0.0, 0.0, 0.0, 0.0, 0.0])  # type: ignore[method-assign]
    conn._poll_recovered_close = MagicMock(  # type: ignore[method-assign]
        return_value={
            "status": "ok",
            "action": "TRADE",
            "type": "CLOSE",
            "ticket": 42818,
            "volume": 22.92,
            "remaining_volume": 0.0,
            "recovered": True,
        },
    )

    with patch("src.bridges.zeromq_connector.time.sleep"):
        result = conn.close_position(42818)

    assert result["status"] == "ok"
    assert result.get("recovered") is True
    assert calls["n"] == 1
