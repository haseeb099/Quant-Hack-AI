"""Tests for agent audit and parameter optimizer."""

from __future__ import annotations

from pathlib import Path

from src.engine.config import QuantAIConfig
from src.learning.agent_audit import AgentAuditor
from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.learning.parameter_optimizer import ParameterOptimizer
from src.learning.regime_boost_optimizer import RegimeBoostOptimizer


def _seed_memory(db: Path) -> LayeredMemory:
    memory = LayeredMemory(db_path=db, round_id="test")
    for i in range(12):
        memory.store_trade(TradeRecord(
            trade_id=str(i),
            symbol="EUR/USD",
            session="london",
            regime="trending" if i % 2 == 0 else "ranging",
            agent="mean_reversion",
            direction="BUY",
            entry_price=1.1,
            exit_price=1.11,
            r_multiple=0.5 if i % 3 else -0.4,
            attribution_json={
                "primary_agent": "mean_reversion",
                "contributing_agents": ["mean_reversion"],
            },
        ))
    memory.rebuild_semantic_layer()
    return memory


def test_agent_audit_report(tmp_path: Path):
    memory = _seed_memory(tmp_path / "mem.db")
    report = AgentAuditor(memory=memory).run()
    assert report["trade_count"] == 12
    assert "mean_reversion" in report["agents"]
    assert report["agents"]["mean_reversion"]["sample_size"] == 12


def test_parameter_optimizer_bounded(tmp_path: Path):
    memory = _seed_memory(tmp_path / "mem2.db")
    config = QuantAIConfig.load()
    opt = ParameterOptimizer(config, memory)
    _tuned, deltas = opt.optimize()
    for _agent, params in deltas.items():
        for _param, delta in params.items():
            assert abs(delta) <= 5


def test_regime_boost_optimizer(tmp_path: Path):
    memory = _seed_memory(tmp_path / "mem3.db")
    config = QuantAIConfig.load()
    opt = RegimeBoostOptimizer(config, memory)
    _boosts, deltas = opt.optimize()
    for _regime, agents in deltas.items():
        for _agent, delta in agents.items():
            assert abs(delta) <= 0.15
