"""Build orchestrator context from market state, memory, and risk."""

from __future__ import annotations

from typing import Any

from src.agents.base_agent import AgentSignal, FeatureVector
from src.learning.layered_memory import LayeredMemory


class ContextBuilder:
    """Assembles context dict for orchestrator (Claude + rule-based)."""

    def __init__(self, memory: LayeredMemory) -> None:
        self.memory = memory

    def build(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        session: str,
        drawdown_pct: float,
        risk_tier: str,
        phase_multiplier: float,
        open_positions: list[dict[str, Any]] | None = None,
        margin_state: Any = None,
        debate: dict[str, Any] | None = None,
        peer_sentiment: str | None = None,
        peer_sizing_adj: float = 1.0,
    ) -> dict[str, Any]:
        regime = features.regime.value
        semantic = self.memory.get_semantic_context(regime, features.symbol, session)
        similar = self.memory.retrieve_similar_setups(regime, features.symbol, session, top_k=5)
        working = self.memory.get_working_memory()

        similar_summary = []
        for s in similar:
            similar_summary.append({
                "agent": s.agent,
                "direction": s.direction,
                "r_multiple": s.r_multiple,
                "exit_time": s.exit_time,
            })

        agent_summary = []
        for sig in signals:
            agent_summary.append({
                "agent": sig.agent_name,
                "direction": sig.direction.value,
                "confidence": sig.confidence,
                "reasoning": sig.reasoning,
            })

        return {
            "symbol": features.symbol,
            "timeframe": features.timeframe,
            "regime": regime,
            "session": session,
            "close": features.close,
            "adx": features.adx,
            "rsi_14": features.rsi_14,
            "atr_14": features.atr_14,
            "volume_ratio": features.volume_ratio,
            "drawdown_pct": drawdown_pct,
            "risk_tier": risk_tier,
            "phase_multiplier": phase_multiplier,
            "semantic_best_agent": semantic.get("best_agent"),
            "semantic_best_score": semantic.get("best_agent_score", 0),
            "semantic_sample_count": semantic.get("sample_count", 0),
            "similar_setups": similar_summary,
            "working_memory": [
                {"symbol": w.symbol, "agent": w.agent, "r_multiple": w.r_multiple}
                for w in working
            ],
            "open_positions": open_positions or [],
            "agent_signals": agent_summary,
            "margin_usage_pct": getattr(margin_state, "margin_usage_pct", 0),
            "effective_leverage": getattr(margin_state, "effective_leverage", 0),
            "debate_winner": (debate or {}).get("winner"),
            "debate_confidence": (debate or {}).get("confidence", 0),
            "debate_synthesis": (debate or {}).get("synthesis", ""),
            "debate_bull": (debate or {}).get("bull_reasoning", ""),
            "debate_bear": (debate or {}).get("bear_reasoning", ""),
            "peer_sentiment": peer_sentiment or "mixed",
            "peer_sizing_adj": peer_sizing_adj,
        }

    def format_for_prompt(self, context: dict[str, Any]) -> str:
        lines = [
            f"Symbol: {context['symbol']} | Regime: {context['regime']} | Session: {context['session']}",
            f"Price: {context['close']:.5f} | ADX: {context['adx']:.1f} | RSI: {context['rsi_14']:.1f}",
            f"Drawdown: {context['drawdown_pct']:.1%} | Risk tier: {context['risk_tier']}",
            f"Phase multiplier: {context['phase_multiplier']}",
        ]
        if context.get("semantic_best_agent"):
            lines.append(
                f"Semantic best agent: {context['semantic_best_agent']} "
                f"(score={context['semantic_best_score']:.2f}, n={context['semantic_sample_count']})"
            )
        for sig in context.get("agent_signals", []):
            lines.append(f"  {sig['agent']}: {sig['direction']} conf={sig['confidence']:.2f} — {sig['reasoning']}")
        if context.get("working_memory"):
            lines.append(f"Recent trades: {len(context['working_memory'])} in working memory")
        return "\n".join(lines)
