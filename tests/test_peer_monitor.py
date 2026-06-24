"""Tests for PeerMonitor catch-up sizing."""

from __future__ import annotations

from src.intelligence.peer_monitor import PeerMonitor


def test_catch_up_multiplier_round2() -> None:
    monitor = PeerMonitor(round_id="round2")
    monitor.update({
        "peer_count": 50,
        "avg_return": 0.10,
        "avg_drawdown": 0.04,
        "top_performer_return": 0.15,
        "our_return": 0.05,
        "our_rank": 40,
    })
    assert monitor.catch_up_multiplier("normal") == 1.15
    assert monitor.catch_up_multiplier("warning") == 1.0


def test_should_increase_aggression_in_round2() -> None:
    monitor = PeerMonitor(round_id="round2")
    monitor.state.crowd_sentiment = "risk_on"
    monitor.state.relative_performance = -0.03
    assert monitor.should_increase_aggression() is True
