"""Tests for Kelly R:R sizing inputs."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.engine.trading_engine import TradingEngine
from src.engine.config import QuantAIConfig


def test_reward_risk_ratio_from_agent_stops():
    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    entry = 1.1000
    sl = 1.0980
    tp = 1.1040
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk
    assert rr == 2.0


def test_agent_win_rate_used_when_samples_sufficient():
    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    engine.memory.agent_performance = MagicMock(
        return_value={"win_rate": 0.62, "sample_size": 8},
    )
    perf = engine.memory.agent_performance("breakout_hunter")
    assert perf["sample_size"] >= 5
    assert perf["win_rate"] == 0.62
