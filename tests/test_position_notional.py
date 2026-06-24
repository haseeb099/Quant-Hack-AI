"""Tests for canonical position notional helpers."""

from __future__ import annotations

import pytest

from src.risk.account_profile import position_notional, position_notional_from_dict
from src.risk.portfolio_heat import PortfolioHeat


def test_fx_notional_uses_contract_size() -> None:
    notional = position_notional(volume=1.0, contract_size=100_000.0, price=1.10)
    assert notional == pytest.approx(110_000.0)


def test_xau_notional() -> None:
    notional = position_notional(volume=0.5, contract_size=100.0, price=2350.0)
    assert notional == 117_500.0


def test_position_notional_from_dict() -> None:
    pos = {"volume": 2.0, "price_open": 95000.0, "type": "BUY", "symbol": "BTC/USD"}
    assert position_notional_from_dict(pos, contract_size=1.0) == 190_000.0


def test_net_directional_with_fx_contract_size() -> None:
    positions = [
        {"symbol": "EUR/USD", "type": "BUY", "volume": 1.0, "price_open": 1.10},
        {"symbol": "GBP/USD", "type": "BUY", "volume": 0.5, "price_open": 1.25},
    ]

    def fx_contract(_symbol: str) -> float:
        return 100_000.0

    ratio = PortfolioHeat.net_directional_ratio(positions, fx_contract)
    assert ratio == 1.0

    mixed = positions + [{"symbol": "USD/JPY", "type": "SELL", "volume": 1.0, "price_open": 150.0}]
    ratio_mixed = PortfolioHeat.net_directional_ratio(mixed, fx_contract)
    assert 0.0 < ratio_mixed < 1.0


def test_ranking_differs_with_without_contract_size() -> None:
    positions = [
        {"symbol": "EUR/USD", "type": "BUY", "volume": 1.0, "price_open": 1.10},
        {"symbol": "BTC/USD", "type": "BUY", "volume": 1.0, "price_open": 95000.0},
    ]

    def lookup(symbol: str) -> float:
        return 100_000.0 if symbol == "EUR/USD" else 1.0

    fx_notional = PortfolioHeat._position_notional(positions[0], lookup)
    btc_notional = PortfolioHeat._position_notional(positions[1], lookup)
    assert fx_notional > btc_notional
