"""Shared types and base class for all trading agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Regime(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CALM = "calm"


@dataclass
class AgentSignal:
    agent_name: str
    symbol: str
    direction: Direction
    confidence: float
    stop_loss: float | None = None
    take_profit: float | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.direction != Direction.HOLD and self.confidence > 0.0


@dataclass
class FeatureVector:
    symbol: str
    timeframe: str
    close: float
    atr_14: float
    atr_50: float
    rsi_14: float
    adx: float
    ema_9: float
    ema_21: float
    ema_50: float
    ema_200: float
    bb_width: float
    bb_width_percentile: float
    donchian_high: float
    donchian_low: float
    volume_ratio: float
    macd_histogram: float
    regime: Regime = Regime.CALM
    extras: dict[str, Any] = field(default_factory=dict)


class BaseTradingAgent(ABC):
    """Abstract base for all rule-based trading agents."""

    name: str = "base"
    base_weight: float = 0.0

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def analyze(self, features: FeatureVector) -> AgentSignal:
        """Generate a trading signal from the current feature vector."""

    def _clamp_confidence(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
