"""Tests for ticket-bound partial close API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.bridges.zeromq_connector import ZeroMQConnector


def test_reduce_position_sends_close_partial() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._connected = True
    conn._bridge_responding = True

    sent: list[dict] = []

    def fake_send(command: dict, *, drain_stale: bool = True) -> dict:
        sent.append(command)
        return {"status": "ok", "remaining_volume": 0.005, "type": "CLOSE_PARTIAL"}

    conn._send_command = fake_send  # type: ignore[method-assign]
    conn.get_symbol_info = MagicMock(  # type: ignore[method-assign]
        return_value={
            "contract_size": 100_000.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        },
    )

    result = conn.reduce_position(ticket=42, volume=0.005, symbol="EUR/USD")

    assert result["status"] == "ok"
    assert len(sent) == 1
    assert sent[0]["type"] == "CLOSE_PARTIAL"
    assert sent[0]["ticket"] == 42
    assert sent[0]["type"] != "BUY"
    assert sent[0]["type"] != "SELL"


def test_reduce_position_simulation() -> None:
    conn = ZeroMQConnector()
    result = conn.reduce_position(99, 0.01, "EUR/USD")
    assert result["status"] == "simulated"
    assert result["type"] == "CLOSE_PARTIAL"


def test_send_trade_retries_on_timeout() -> None:
    conn = ZeroMQConnector()
    conn._sockets_ready = True
    conn._connected = True
    conn._bridge_responding = True
    calls = {"n": 0}

    def flaky_send(command: dict, *, drain_stale: bool = True) -> dict:
        calls["n"] += 1
        if calls["n"] < 2:
            return {"status": "error", "message": "Request timed out"}
        return {"status": "ok", "action": "TRADE"}

    conn._send_command = flaky_send  # type: ignore[method-assign]
    conn._mt5_volume_for_symbol_direction = MagicMock(return_value=0.0)  # type: ignore[method-assign]
    conn._poll_recovered_open_trade = MagicMock(return_value=None)  # type: ignore[method-assign]
    conn._recover_open_trade_result = MagicMock(return_value=None)  # type: ignore[method-assign]

    with patch("src.bridges.zeromq_connector.time.sleep"):
        result = conn._send_with_retry({"action": "TRADE", "type": "BUY", "symbol": "EUR/USD", "volume": 0.1})

    assert result["status"] == "ok"
    assert calls["n"] == 2
