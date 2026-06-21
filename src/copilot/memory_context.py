"""Agentic memory snapshot for dashboard and copilot — grounded, cited."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.data.session_filter import SessionFilter
from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.web.runtime_state import read_state


def _trade_summary(record: TradeRecord) -> dict[str, Any]:
    return {
        "trade_id": record.trade_id,
        "symbol": record.symbol,
        "session": record.session,
        "regime": record.regime,
        "agent": record.agent,
        "direction": record.direction,
        "r_multiple": record.r_multiple,
        "pnl": record.pnl,
        "entry_time": record.entry_time,
        "exit_time": record.exit_time,
    }


def _semantic_agents_table(semantic: dict[str, Any]) -> list[dict[str, Any]]:
    agents = semantic.get("agents") or {}
    rows: list[dict[str, Any]] = []
    for agent, stats in agents.items():
        total = int(stats.get("total", 0))
        if total <= 0:
            continue
        wins = int(stats.get("wins", 0))
        rows.append({
            "agent": agent,
            "trades": total,
            "win_rate": wins / total,
            "avg_r": float(stats.get("avg_r", 0)),
        })
    rows.sort(key=lambda r: r["win_rate"] * 0.6 + r["avg_r"] * 0.4, reverse=True)
    return rows


class MemoryContextBuilder:
    """Assemble working, episodic, and semantic memory for API/copilot."""

    def __init__(self, memory: LayeredMemory | None = None) -> None:
        self.memory = memory or LayeredMemory()
        self.session_filter = SessionFilter()

    def build(
        self,
        symbol: str | None = None,
        regime: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = state or read_state()
        session = self.session_filter.session_name()
        working = [_trade_summary(t) for t in self.memory.get_working_memory()]

        semantic: dict[str, Any] = {}
        similar: list[dict[str, Any]] = []
        resolved_regime = regime

        if symbol:
            instruments = state.get("instruments", {})
            inst = instruments.get(symbol, {})
            if not resolved_regime:
                resolved_regime = str(inst.get("last_regime") or "ranging")

            semantic_raw = self.memory.get_semantic_context(
                resolved_regime, symbol, session,
            )
            semantic = {
                "symbol": symbol,
                "regime": resolved_regime,
                "session": session,
                "best_agent": semantic_raw.get("best_agent"),
                "best_agent_score": semantic_raw.get("best_agent_score", 0),
                "sample_count": semantic_raw.get("sample_count", 0),
                "agents": _semantic_agents_table(semantic_raw),
                "min_samples": self.memory.MIN_SEMANTIC_SAMPLES,
            }
            similar = [
                _trade_summary(t)
                for t in self.memory.retrieve_similar_setups(
                    resolved_regime, symbol, session, top_k=3,
                )
            ]

        return {
            "session": session,
            "symbol": symbol,
            "working_memory": working,
            "semantic": semantic,
            "similar_setups": similar,
            "total_trades_in_db": self.memory.trade_count(),
            "layers": {
                "working": len(working),
                "episodic": self.memory.trade_count(),
                "semantic_keys": self.memory.semantic_key_count(),
            },
        }

    def memory_summary_line(self, context: dict[str, Any]) -> str | None:
        """One-line grounded memory note for copilot narrative."""
        semantic = context.get("semantic") or {}
        if semantic.get("best_agent") and semantic.get("sample_count", 0) >= self.memory.MIN_SEMANTIC_SAMPLES:
            best = semantic["best_agent"]
            n = semantic["sample_count"]
            score = float(semantic.get("best_agent_score", 0))
            return (
                f"Semantic memory ({n} samples, {semantic.get('regime')} · {semantic.get('session')}): "
                f"best agent {best} (score {score:.2f})."
            )
        working = context.get("working_memory") or []
        if working:
            last = working[-1]
            return (
                f"Working memory: last closed {last.get('symbol')} {last.get('direction')} "
                f"R={last.get('r_multiple')} via {last.get('agent')}."
            )
        if context.get("total_trades_in_db", 0) == 0:
            return "Memory layers empty — no closed trades recorded yet."
        return None
