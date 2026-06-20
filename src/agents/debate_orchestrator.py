"""Bull/Bear debate orchestrator — P2 SOTA upgrade."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.agents.base_agent import AgentSignal, Direction, FeatureVector

logger = logging.getLogger(__name__)


@dataclass
class DebateArgument:
    side: str  # "bull" or "bear"
    confidence: float
    reasoning: str
    key_factors: list[str]


@dataclass
class DebateResult:
    symbol: str
    bull_case: DebateArgument
    bear_case: DebateArgument
    winner: str
    direction: Direction
    confidence: float
    synthesis: str


class DebateOrchestrator:
    """Runs bull vs bear debate before orchestrator decision."""

    def debate(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> DebateResult:
        bull_factors: list[str] = []
        bear_factors: list[str] = []
        bull_score = 0.0
        bear_score = 0.0

        for sig in signals:
            if sig.direction == Direction.BUY:
                bull_score += sig.confidence
                bull_factors.append(f"{sig.agent_name}: {sig.reasoning}")
            elif sig.direction == Direction.SELL:
                bear_score += sig.confidence
                bear_factors.append(f"{sig.agent_name}: {sig.reasoning}")

        if features.rsi_14 < 30:
            bull_score += 0.2
            bull_factors.append(f"RSI oversold at {features.rsi_14:.1f}")
        if features.rsi_14 > 70:
            bear_score += 0.2
            bear_factors.append(f"RSI overbought at {features.rsi_14:.1f}")

        if features.ema_9 > features.ema_21:
            bull_score += 0.15
            bull_factors.append("EMA momentum bullish")
        elif features.ema_9 < features.ema_21:
            bear_score += 0.15
            bear_factors.append("EMA momentum bearish")

        if context and context.get("semantic_best_agent"):
            best = context["semantic_best_agent"]
            for sig in signals:
                if sig.agent_name == best and sig.is_actionable:
                    if sig.direction == Direction.BUY:
                        bull_score += 0.1
                    elif sig.direction == Direction.SELL:
                        bear_score += 0.1

        bull_case = DebateArgument(
            side="bull",
            confidence=min(bull_score, 1.0),
            reasoning="; ".join(bull_factors) or "No bullish factors",
            key_factors=bull_factors,
        )
        bear_case = DebateArgument(
            side="bear",
            confidence=min(bear_score, 1.0),
            reasoning="; ".join(bear_factors) or "No bearish factors",
            key_factors=bear_factors,
        )

        if bull_score > bear_score and bull_score > 0.3:
            winner = "bull"
            direction = Direction.BUY
            confidence = min(bull_score / max(len(signals), 1), 1.0)
        elif bear_score > bull_score and bear_score > 0.3:
            winner = "bear"
            direction = Direction.SELL
            confidence = min(bear_score / max(len(signals), 1), 1.0)
        else:
            winner = "neutral"
            direction = Direction.HOLD
            confidence = 0.0

        synthesis = f"Bull {bull_score:.2f} vs Bear {bear_score:.2f} -> {winner}"

        return DebateResult(
            symbol=features.symbol,
            bull_case=bull_case,
            bear_case=bear_case,
            winner=winner,
            direction=direction,
            confidence=confidence,
            synthesis=synthesis,
        )
