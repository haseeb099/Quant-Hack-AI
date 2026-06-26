"""Tests for audit-driven entry quality scoring."""

from __future__ import annotations

from src.learning.entry_quality import score_entry


def test_two_agent_audit_winner_passes() -> None:
    q = score_entry(
        symbol="USD/CAD",
        direction="BUY",
        regime="trending",
        adx=32.0,
        rsi=55.0,
        confidence=0.80,
        agreeing_agents=["trend_surfer", "ml_signal"],
        symbol_rates={"trend_surfer": 0.57, "ml_signal": 0.55},
        audit_rates={},
        debate_confirms=True,
    )
    assert q.passed
    assert q.score >= 0.72
    assert q.tier in ("silver", "gold")


def test_fx_short_in_ranging_fails() -> None:
    q = score_entry(
        symbol="USD/CAD",
        direction="SELL",
        regime="ranging",
        adx=18.0,
        rsi=46.0,
        confidence=0.76,
        agreeing_agents=["trend_surfer"],
        symbol_rates={"trend_surfer": 0.57},
        audit_rates={},
        debate_confirms=True,
    )
    assert not q.passed
    assert q.tier == "reject"


def test_metal_buy_calm_fails() -> None:
    q = score_entry(
        symbol="XAU/USD",
        direction="BUY",
        regime="calm",
        adx=17.0,
        rsi=50.0,
        confidence=0.66,
        agreeing_agents=["ml_signal"],
        symbol_rates={"ml_signal": 0.75},
        audit_rates={},
        debate_confirms=True,
    )
    assert not q.passed


def test_solo_ml_metal_sell_trending_can_pass() -> None:
    q = score_entry(
        symbol="XAU/USD",
        direction="SELL",
        regime="trending",
        adx=35.0,
        rsi=42.0,
        confidence=0.88,
        agreeing_agents=["ml_signal"],
        symbol_rates={"ml_signal": 0.75},
        audit_rates={},
        debate_confirms=True,
        solo_metal_sell_ok=True,
    )
    assert q.passed
    assert q.score >= 0.68


def test_audit_solo_trend_surfer_trending_can_pass() -> None:
    q = score_entry(
        symbol="USD/CAD",
        direction="SELL",
        regime="trending",
        adx=31.0,
        rsi=44.0,
        confidence=0.76,
        agreeing_agents=["trend_surfer"],
        symbol_rates={"trend_surfer": 0.57},
        audit_rates={},
        debate_confirms=True,
        audit_solo_trend_surfer_ok=True,
    )
    assert q.passed
    assert q.score >= 0.68
