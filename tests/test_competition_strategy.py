"""Tests for audit-driven competition strategy."""

from __future__ import annotations

from src.learning.competition_strategy import CompetitionStrategy, TIER_A_SYMBOLS


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
