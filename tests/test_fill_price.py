"""Tests for fill price resolution."""

from __future__ import annotations

from src.bridges.fill_price import resolve_fill_price


class _StubConnector:
    def __init__(self, positions: list[dict]) -> None:
        self._positions = positions

    def get_positions(self) -> list[dict]:
        return self._positions


def test_uses_result_price_when_positive() -> None:
    conn = _StubConnector([])
    price = resolve_fill_price({"price": 1.2345, "ticket": 10}, 10, "EUR/USD", 1.0, conn)
    assert price == 1.2345


def test_polls_mt5_when_result_price_zero() -> None:
    conn = _StubConnector([{"ticket": 123, "price_open": 0.86243}])
    price = resolve_fill_price({"price": 0.0, "ticket": 123}, 123, "EUR/GBP", 0.85, conn)
    assert price == 0.86243


def test_falls_back_to_executable_price() -> None:
    conn = _StubConnector([])
    price = resolve_fill_price({"price": 0.0}, None, "USD/JPY", 161.587, conn)
    assert price == 161.587


def test_does_not_use_slippage_as_fill() -> None:
    conn = _StubConnector([])
    price = resolve_fill_price({"price": 0.0, "slippage": 0.00012}, None, "EUR/USD", 1.105, conn)
    assert price == 1.105
