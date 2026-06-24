"""Tests for trade attribution and agent health."""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.base_agent import Direction
from src.learning.layered_memory import LayeredMemory, TradeRecord, build_trade_attribution
from src.operator.agent_health import AgentHealthSuite


class _FakeSignal:
    def __init__(self, agent_name: str, direction: Direction, confidence: float, actionable: bool = True):
        self.agent_name = agent_name
        self.direction = direction
        self.confidence = confidence
        self.is_actionable = actionable


def test_build_trade_attribution():
    signals = [
        _FakeSignal("trend_surfer", Direction.BUY, 0.8),
        _FakeSignal("momentum_pulse", Direction.BUY, 0.7),
        _FakeSignal("mean_reversion", Direction.SELL, 0.6),
    ]
    attr = build_trade_attribution(
        signals=signals,
        decision_direction="BUY",
        primary_agent="trend_surfer",
        orchestrator_used_ai=False,
        semantic_best_agent="momentum_pulse",
    )
    assert attr["primary_agent"] == "trend_surfer"
    assert set(attr["contributing_agents"]) == {"trend_surfer", "momentum_pulse"}
    assert attr["vote_consensus"]["buy"] == 2
    assert attr["vote_consensus"]["sell"] == 1


def test_agent_vote_attribution(tmp_path: Path):
    db = tmp_path / "trade_memory.db"
    memory = LayeredMemory(db_path=db, round_id="test")
    for i, r in enumerate([1.2, -0.8, 0.5]):
        memory.store_trade(TradeRecord(
            trade_id=str(i),
            symbol="EUR/USD",
            session="london",
            regime="trending",
            agent="trend_surfer",
            direction="BUY",
            entry_price=1.1,
            exit_price=1.11,
            r_multiple=r,
            attribution_json={
                "contributing_agents": ["trend_surfer", "momentum_pulse"],
                "primary_agent": "trend_surfer",
            },
        ))
    perf = memory.agent_vote_attribution("momentum_pulse")
    assert perf["sample_size"] >= 2
    assert perf["win_rate"] is not None


def test_agent_health_suite_runs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_ENABLED", "true")
    suite = AgentHealthSuite(data_dir=tmp_path)
    report = suite.run(symbols=["EUR/USD", "GBP/USD"])
    assert report["status"] in ("GREEN", "YELLOW", "RED")
    assert "trend_surfer" in report["agents"]
    assert report["agents"]["trend_surfer"]["symbols_tested"] == 2


def test_agent_health_persist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_ENABLED", "true")
    out = tmp_path / "agent_health.json"
    from src.operator.agent_health import run_agent_health

    report = run_agent_health(output_path=out, data_dir=tmp_path, persist=True)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["status"] == report["status"]
