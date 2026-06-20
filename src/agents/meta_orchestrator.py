"""Meta-orchestrator — Claude-powered with rule-based fallback."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from src.agents.base_agent import AgentSignal, Direction, FeatureVector, Regime

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorDecision:
    symbol: str
    direction: Direction
    confidence: float
    size_scale: float
    reasoning: str
    risk_assessment: str = ""
    urgency: str = "normal"
    agent_votes: list[AgentSignal] | None = None
    used_ai: bool = False


class MetaOrchestrator:
    """Aggregates agent signals into a final trading decision.

    Uses Claude when available; falls back to regime-weighted voting.
    """

    def __init__(self, config: dict[str, Any], regime_boosts: dict[str, dict[str, float]]) -> None:
        self.config = config
        self.regime_boosts = regime_boosts
        self._anthropic_key = config.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")
        self._doubleword_key = os.getenv("DOUBLEWORD_API_KEY")
        self._groq_key = os.getenv("GROQ_API_KEY") or os.getenv("Groq_API_KEY")
        self._use_ai = bool(self._anthropic_key or self._doubleword_key or self._groq_key) and self._has_pydantic_ai()
        self._cooldown_minutes = config.get("cooldown_minutes", 5)
        self._last_ai_call: dict[str, float] = {}

    @staticmethod
    def _has_pydantic_ai() -> bool:
        try:
            import pydantic_ai  # noqa: F401
            return True
        except ImportError:
            return False

    def decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        drawdown_tier: str = "normal",
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        actionable = [s for s in signals if s.is_actionable]
        min_conf = float(
            os.getenv(
                "QUANTAI_MIN_CONFIDENCE",
                self.config.get("min_agent_confidence", 0.65),
            )
        )

        if not actionable or max(s.confidence for s in actionable) < min_conf:
            return OrchestratorDecision(
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                size_scale=0.0,
                reasoning="No agent above minimum confidence threshold",
                agent_votes=signals,
            )

        if drawdown_tier in ("critical", "emergency"):
            return OrchestratorDecision(
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                size_scale=0.0,
                reasoning=f"Drawdown tier {drawdown_tier} — no new trades",
                agent_votes=signals,
            )

        if self._use_ai and self._can_call_ai(features.symbol):
            try:
                return self._ai_decide(features, actionable, context)
            except Exception:
                logger.warning("AI decision failed, falling back to rule-based", exc_info=True)

        return self._rule_based_decide(features, actionable, context)

    def _can_call_ai(self, symbol: str) -> bool:
        now = time.time()
        last = self._last_ai_call.get(symbol, 0)
        return (now - last) >= self._cooldown_minutes * 60

    def _rule_based_decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        regime_key = features.regime.value
        boosts = self.regime_boosts.get(regime_key, {})
        min_conf = self.config.get("min_agent_confidence", 0.65)

        buy_score = 0.0
        sell_score = 0.0
        for signal in signals:
            boost = boosts.get(signal.agent_name, 1.0)
            weighted = signal.confidence * boost
            if signal.direction == Direction.BUY:
                buy_score += weighted
            elif signal.direction == Direction.SELL:
                sell_score += weighted

        if buy_score > sell_score and buy_score > 0:
            direction = Direction.BUY
            confidence = min(buy_score / len(signals), 1.0)
            reasoning = f"Regime-weighted BUY ({regime_key}): score {buy_score:.2f}"
        elif sell_score > buy_score and sell_score > 0:
            direction = Direction.SELL
            confidence = min(sell_score / len(signals), 1.0)
            reasoning = f"Regime-weighted SELL ({regime_key}): score {sell_score:.2f}"
        else:
            direction = Direction.HOLD
            confidence = 0.0
            reasoning = "Conflicting signals — holding"

        directions = {s.direction for s in signals if s.is_actionable}
        size_scale = 0.7 if len(directions) > 1 else 1.0

        if context and context.get("semantic_best_agent"):
            best = context["semantic_best_agent"]
            for sig in signals:
                if sig.agent_name == best and sig.is_actionable:
                    confidence = min(confidence * 1.05, 1.0)
                    reasoning += f"; semantic boost for {best}"

        if context and context.get("debate_winner") in ("bull", "bear"):
            debate_dir = Direction.BUY if context["debate_winner"] == "bull" else Direction.SELL
            debate_conf = context.get("debate_confidence", 0)
            if debate_conf >= min_conf and debate_dir == direction:
                confidence = min(max(confidence, debate_conf), 1.0)
                reasoning += f"; debate confirms {context['debate_winner']}"
            elif debate_conf >= min_conf and direction != Direction.HOLD and debate_dir != direction:
                size_scale *= 0.6
                reasoning += "; debate conflicts — reduced size"

        return OrchestratorDecision(
            symbol=features.symbol,
            direction=direction,
            confidence=confidence,
            size_scale=size_scale,
            reasoning=reasoning,
            risk_assessment=f"Regime: {regime_key}",
            agent_votes=signals,
        )

    def _ai_decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent

        class AIDecision(BaseModel):
            direction: str = Field(description="BUY, SELL, or HOLD")
            confidence: float = Field(ge=0, le=1)
            size_scale: float = Field(ge=0.5, le=1.5, default=1.0)
            reasoning: str = ""
            risk_assessment: str = ""

        model_name = self.config.get("model", "claude-sonnet-4-20250514")
        temperature = self.config.get("temperature", 0.1)

        if self._doubleword_key:
            model = "openai:gpt-4o-mini"
            os.environ.setdefault("OPENAI_API_KEY", self._doubleword_key)
            os.environ.setdefault("OPENAI_BASE_URL", "https://api.doubleword.ai/v1")
        elif self._groq_key:
            model = "openai:llama-3.3-70b-versatile"
            os.environ.setdefault("OPENAI_API_KEY", self._groq_key)
            os.environ.setdefault("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
        else:
            model = f"anthropic:{model_name}"

        prompt_parts = [
            "You are the MetaOrchestrator for a competition trading system.",
            f"Symbol: {features.symbol}, Regime: {features.regime.value}",
            f"ADX: {features.adx:.1f}, RSI: {features.rsi_14:.1f}, ATR: {features.atr_14:.4f}",
        ]
        for sig in signals:
            prompt_parts.append(
                f"Agent {sig.agent_name}: {sig.direction.value} conf={sig.confidence:.2f} — {sig.reasoning}"
            )
        if context:
            if context.get("semantic_best_agent"):
                prompt_parts.append(f"Semantic best agent: {context['semantic_best_agent']}")
            if context.get("working_memory"):
                prompt_parts.append(f"Recent trades: {len(context['working_memory'])}")
            if context.get("drawdown_pct"):
                prompt_parts.append(f"Drawdown: {context['drawdown_pct']:.1%}")
            if context.get("debate_synthesis"):
                prompt_parts.append(f"Bull/Bear debate: {context['debate_synthesis']}")
            if context.get("peer_sentiment"):
                prompt_parts.append(f"Peer crowd sentiment: {context['peer_sentiment']}")

        agent = Agent(model, output_type=AIDecision, system_prompt="Respond with structured trading decisions only.")
        result = agent.run_sync("\n".join(prompt_parts))

        self._last_ai_call[features.symbol] = time.time()
        ai = result.output

        direction_map = {
            "BUY": Direction.BUY,
            "SELL": Direction.SELL,
            "HOLD": Direction.HOLD,
        }
        direction = direction_map.get(ai.direction.upper(), Direction.HOLD)

        return OrchestratorDecision(
            symbol=features.symbol,
            direction=direction,
            confidence=ai.confidence,
            size_scale=ai.size_scale,
            reasoning=ai.reasoning,
            risk_assessment=ai.risk_assessment,
            agent_votes=signals,
            used_ai=True,
        )
