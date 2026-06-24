"""Tests for portfolio heat correlation enforcement."""

from __future__ import annotations

from src.risk.portfolio_heat import PortfolioHeat


def test_blocks_correlated_forex_exposure():
    heat = PortfolioHeat({
        "reference_equity": 100_000,
        "correlation_threshold": 0.70,
        "cluster_cap": 0.40,
    })
    positions = [
        {
            "symbol": "EUR/USD",
            "type": "BUY",
            "volume": 3.0,
            "price_open": 1.10,
            "contract_size": 100_000.0,
        }
    ]
    ok, reason = heat.pre_trade_check(
        equity=100_000,
        positions=positions,
        gross_exposure=330_000,
        symbol="GBP/USD",
        direction="BUY",
        trade_notional=330_000,
        volume=3.0,
        price=1.10,
        contract_size=100_000.0,
        get_contract_size=lambda _s: 100_000.0,
    )
    assert ok is False
    assert reason is not None
    assert "Correlated exposure" in reason


def test_allows_uncorrelated_pair():
    heat = PortfolioHeat({
        "reference_equity": 100_000,
        "correlation_threshold": 0.70,
        "cluster_cap": 0.40,
    })
    ok, reason = heat.pre_trade_check(
        equity=100_000,
        positions=[],
        gross_exposure=0,
        symbol="XAU/USD",
        direction="BUY",
        trade_notional=5_000,
        volume=0.02,
        price=2350.0,
        contract_size=100.0,
        get_contract_size=lambda s: 100.0 if s == "XAU/USD" else 100_000.0,
    )
    assert ok is True
    assert reason is None


def test_blocks_stacked_chf_cluster():
    heat = PortfolioHeat({
        "reference_equity": 100_000,
        "chf_cluster_max_pct": 0.35,
        "cluster_cap": 0.40,
        "correlation_threshold": 0.99,
    })
    positions = [{
        "symbol": "USD/CHF",
        "type": "SELL",
        "volume": 2.0,
        "price_open": 0.90,
        "contract_size": 100_000.0,
    }]
    ok, reason = heat.pre_trade_check(
        equity=100_000,
        positions=positions,
        gross_exposure=180_000,
        symbol="EUR/CHF",
        direction="SELL",
        trade_notional=200_000,
        volume=2.0,
        price=1.0,
        contract_size=100_000.0,
        get_contract_size=lambda _s: 100_000.0,
    )
    assert ok is False
    assert reason is not None
    assert "CHF cluster" in reason


def test_blocks_metals_single_symbol_cap():
    heat = PortfolioHeat({
        "reference_equity": 100_000,
        "metals_single_max_pct": 0.25,
        "metals_cluster_max_pct": 0.50,
        "cluster_cap": 0.40,
    })
    ok, reason = heat.pre_trade_check(
        equity=100_000,
        positions=[],
        gross_exposure=0,
        symbol="XAU/USD",
        direction="BUY",
        trade_notional=30_000,
        volume=0.12,
        price=2500.0,
        contract_size=100.0,
        get_contract_size=lambda _s: 100.0,
    )
    assert ok is False
    assert "Metals single-symbol" in reason


def test_blocks_stacked_chf_cluster_exposure():
    heat = PortfolioHeat({
        "reference_equity": 100_000,
        "chf_cluster_max_pct": 0.35,
    })
    positions = [
        {
            "symbol": "USD/CHF",
            "type": "SELL",
            "volume": 0.20,
            "price_open": 0.90,
            "contract_size": 100_000.0,
        },
        {
            "symbol": "EUR/CHF",
            "type": "BUY",
            "volume": 0.20,
            "price_open": 0.95,
            "contract_size": 100_000.0,
        },
    ]
    gross = 18_000 + 19_000
    state = heat.assess(100_000, positions, gross)
    assert state.allow_trade is False
    assert state.block_reason is not None
    assert "CHF cluster" in state.block_reason
