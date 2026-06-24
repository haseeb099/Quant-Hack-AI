"""Tests for concentration lot cap before order send."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.engine.config import QuantAIConfig
from src.engine.trading_engine import TradingEngine


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SENTIMENT_AGENT_ENABLED", "false")
    config = QuantAIConfig.load(phase="round1", auto_phase=False)
    eng = TradingEngine(config=config, simulation=True)
    eng._get_symbol_specs = MagicMock(  # type: ignore[method-assign]
        return_value={
            "contract_size": 100_000.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        },
    )
    return eng


def test_cap_allows_fresh_entry_up_to_40pct(engine) -> None:
    equity = 1_000_000.0
    price = 0.70
    lots = 5.70  # 399k notional — within 40% cap
    capped = engine._cap_lots_to_concentration("AUD/USD", lots, price, equity, [])
    assert capped == pytest.approx(5.70)


def test_cap_shrinks_oversized_fresh_entry(engine) -> None:
    equity = 1_000_000.0
    price = 0.70
    lots = 10.0  # ~700k notional > 40%
    capped = engine._cap_lots_to_concentration("AUD/USD", lots, price, equity, [])
    assert capped == pytest.approx(5.71)


def test_cap_blocks_add_when_symbol_already_at_cap(engine) -> None:
    equity = 1_000_000.0
    price = 0.70
    open_positions = [{
        "symbol": "AUD/USD",
        "volume": 22.92,
        "price_open": price,
        "contract_size": 100_000.0,
    }]
    capped = engine._cap_lots_to_concentration("AUD/USD", 5.73, price, equity, open_positions)
    assert capped == 0.0


def test_cap_allows_partial_room_on_existing_symbol(engine) -> None:
    equity = 1_000_000.0
    price = 0.70
    open_positions = [{
        "symbol": "AUDUSD",
        "volume": 2.86,
        "price_open": price,
        "contract_size": 100_000.0,
    }]
    capped = engine._cap_lots_to_concentration("AUD/USD", 5.73, price, equity, open_positions)
    assert capped == pytest.approx(2.85)


def test_cap_metals_uses_single_symbol_limit(engine) -> None:
    equity = 1_000_000.0
    price = 2500.0
    engine._get_symbol_specs = MagicMock(  # type: ignore[method-assign]
        return_value={
            "contract_size": 100.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        },
    )
    lots = 1.2  # 300k notional > 25% cap
    capped = engine._cap_lots_to_concentration("XAU/USD", lots, price, equity, [])
    assert capped == pytest.approx(1.0)


def test_cap_does_not_ratchet_with_oversized_other_symbol(engine) -> None:
    equity = 1_000_000.0
    price_eur = 1.10
    open_positions = [{
        "symbol": "AUD/USD",
        "volume": 22.92,
        "price_open": 0.70,
        "contract_size": 100_000.0,
    }]
    lots = 3.64  # ~400k EUR notional at 1.10
    capped = engine._cap_lots_to_concentration("EUR/USD", lots, price_eur, equity, open_positions)
    assert capped == pytest.approx(3.63)
