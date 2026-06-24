"""Regime boost tuner using semantic memory stats."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory

logger = logging.getLogger(__name__)

MAX_BOOST_DELTA = 0.15
MIN_WIN_RATE = 0.35
MIN_SAMPLES = 10


class RegimeBoostOptimizer:
    """Adjust regime boosts based on per-regime agent win rates."""

    def __init__(
        self,
        config: QuantAIConfig | None = None,
        memory: LayeredMemory | None = None,
    ) -> None:
        self.config = config or QuantAIConfig.load()
        self.memory = memory or LayeredMemory()

    def optimize(self) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
        """Return (new_boosts, boost_deltas)."""
        base = deepcopy(self.config.regime_boosts)
        tuned = deepcopy(base)
        deltas: dict[str, dict[str, float]] = {}

        for regime, boosts in base.items():
            for agent, boost in boosts.items():
                perf = self.memory.agent_performance(agent, regime=regime)
                n = perf.get("sample_size") or 0
                wr = perf.get("win_rate")
                if n < MIN_SAMPLES or wr is None:
                    continue
                delta = 0.0
                if wr < MIN_WIN_RATE:
                    delta = -min(MAX_BOOST_DELTA, (MIN_WIN_RATE - wr) * 0.5)
                elif wr > 0.55:
                    delta = min(MAX_BOOST_DELTA, (wr - 0.55) * 0.3)
                if abs(delta) < 0.01:
                    continue
                new_boost = max(0.3, min(2.0, boost + delta))
                tuned[regime][agent] = round(new_boost, 3)
                deltas.setdefault(regime, {})[agent] = round(new_boost - boost, 3)

        return tuned, deltas
