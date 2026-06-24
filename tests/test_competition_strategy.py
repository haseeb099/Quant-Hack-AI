"""Tests for audit-driven competition strategy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.learning.competition_strategy import CompetitionStrategy, TIER_A_SYMBOLS


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class _Signal:
    agent_name: str
    direction: Direction
    confidence: float
    is_actionable: bool = True


def test_symbol_tier_a() -> None:
    strat = CompetitionStrategy()
    assert strat.symbol_tier("XAG/USD") == "A"
    assert strat.symbol_tier("USD/CAD") == "A"
    assert "XAG/USD" in TIER_A_SYMBOLS


def test_block_agent_from_audit() -> None:
    strat = CompetitionStrategy(min_samples_block=2, block_win_rate=0.34)
    # EUR/GBP trend_surfer: 0% over 5 trades in agent_audit.json
    assert strat.block_agent("EUR/GBP", "trend_surfer") is True
    assert strat.block_agent("XAG/USD", "trend_surfer") is False


def test_min_consensus_tiering() -> None:
    strat = CompetitionStrategy()
    assert strat.min_consensus_for_symbol("XAG/USD", 1) == 1
    assert strat.min_consensus_for_symbol("EUR/CHF", 1) == 2


def test_tier_a_plus_size_boost_qualifies() -> None:
    strat = CompetitionStrategy()
    signals = [
        _Signal("trend_surfer", Direction.BUY, 0.82),
        _Signal("ml_signal", Direction.BUY, 0.88),
        _Signal("momentum_pulse", Direction.BUY, 0.70),
    ]
    live_filters = {
        "tier_a_plus_size_boost": {
            "enabled": True,
            "min_consensus_agents": 3,
            "min_confidence": 0.85,
            "require_technical_agents": 2,
        },
    }

    def _technical(signal: _Signal) -> bool:
        return signal.agent_name in {"trend_surfer", "ml_signal", "momentum_pulse"}

    boost = strat.tier_a_plus_size_boost(
        "USD/CAD",
        "BUY",
        0.90,
        signals,
        live_filters,
        counts_as_technical=_technical,
    )
    assert boost is not None
    assert boost["max_fx_lots"] is None or boost["max_fx_lots"] > 0
    assert boost["orchestrator_scale_mult"] >= 1.35


def test_tier_a_plus_size_boost_rejects_weak_setup() -> None:
    strat = CompetitionStrategy()
    signals = [
        _Signal("trend_surfer", Direction.BUY, 0.82),
        _Signal("ml_signal", Direction.SELL, 0.88),
    ]
    live_filters = {"tier_a_plus_size_boost": {"enabled": True}}

    boost = strat.tier_a_plus_size_boost(
        "USD/CAD",
        "BUY",
        0.90,
        signals,
        live_filters,
        counts_as_technical=lambda s: True,
    )
    assert boost is None


def test_audit_winner_size_boost_qualifies() -> None:
    strat = CompetitionStrategy()
    signals = [
        _Signal("trend_surfer", Direction.BUY, 0.82),
        _Signal("ml_signal", Direction.BUY, 0.84),
    ]
    live_filters = {
        "audit_winner_symbols": ["USD/CAD", "XAG/USD", "AUD/USD"],
        "audit_winner_size_boost": {
            "enabled": True,
            "min_consensus_agents": 2,
            "min_confidence": 0.80,
            "require_technical_agents": 2,
        },
    }

    boost = strat.resolve_size_boost(
        "USD/CAD",
        "BUY",
        0.86,
        signals,
        live_filters,
        counts_as_technical=lambda s: s.agent_name in {"trend_surfer", "ml_signal"},
    )
    assert boost is not None
    assert boost["boost_tier"] == "audit_winner"


def test_resolve_size_boost_prefers_tier_a_plus() -> None:
    strat = CompetitionStrategy()
    signals = [
        _Signal("trend_surfer", Direction.BUY, 0.86),
        _Signal("ml_signal", Direction.BUY, 0.88),
        _Signal("momentum_pulse", Direction.BUY, 0.72),
    ]
    live_filters = {
        "audit_winner_symbols": ["USD/CAD"],
        "audit_winner_size_boost": {"enabled": True, "min_confidence": 0.80},
        "tier_a_plus_size_boost": {"enabled": True, "min_confidence": 0.85, "min_consensus_agents": 3},
    }

    boost = strat.resolve_size_boost(
        "USD/CAD",
        "BUY",
        0.90,
        signals,
        live_filters,
        counts_as_technical=lambda s: True,
    )
    assert boost is not None
    assert boost["boost_tier"] == "tier_a_plus"
