"""Tests for account_equity helper — no silent fallback in live mode."""

from __future__ import annotations

from src.bridges.zeromq_connector import ZeroMQConnector, account_equity


def test_account_equity_simulation_allows_default() -> None:
    assert account_equity({"status": "simulated", "equity": 1_000_000}, simulation=True) == 1_000_000
    assert account_equity({}, simulation=True) == 1_000_000


def test_account_equity_live_error_returns_none() -> None:
    assert account_equity({"status": "error", "message": "timeout"}, simulation=False) is None
    assert account_equity({"status": "ok"}, simulation=False) is None


def test_account_equity_live_ok() -> None:
    assert account_equity({"status": "ok", "equity": 42_000}, simulation=False) == 42_000


def test_get_account_info_returns_error_when_sockets_not_ready() -> None:
    conn = ZeroMQConnector()
    info = conn.get_account_info()
    assert info["status"] == "error"
    assert "equity" not in info or info.get("equity") is None
