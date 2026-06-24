"""Offline agent weight optimization between competition rounds."""

from __future__ import annotations

from typing import Any

from src.learning.layered_memory import LayeredMemory


class WeightOptimizer:
    """Adjusts agent weights based on trade memory performance.

    Only runs offline between rounds. Caps changes at ±10% per round.
    """

    MAX_WEIGHT_CHANGE = 0.10
    MIN_SAMPLES = 5

    def __init__(self, base_weights: dict[str, float], memory: LayeredMemory) -> None:
        self.base_weights = base_weights
        self.memory = memory

    def _semantic_win_rate(self, agent: str, regime: str | None) -> float | None:
        total = 0
        wins = 0
        for key, data in self.memory._semantic.items():
            if regime and not key.startswith(f"{regime}|"):
                continue
            stats = data.get("agents", {}).get(agent)
            if not stats or stats["total"] < self.MIN_SAMPLES:
                continue
            total += stats["total"]
            wins += stats["wins"]
        if total < self.MIN_SAMPLES:
            return None
        return wins / total

    def optimize(self, regime: str | None = None) -> dict[str, float]:
        new_weights: dict[str, float] = {}
        total = 0.0

        for agent, base_weight in self.base_weights.items():
            perf = self.memory.agent_performance(agent, regime)
            attr = self.memory.agent_vote_attribution(agent, regime)
            if perf["sample_size"] < self.MIN_SAMPLES:
                new_weights[agent] = base_weight
            else:
                global_wr = perf["win_rate"] or 0.5
                semantic_wr = self._semantic_win_rate(agent, regime) or global_wr
                attr_wr = attr.get("win_rate") or global_wr
                factor = 0.4 * global_wr + 0.4 * semantic_wr + 0.2 * attr_wr
                factor = 0.5 + factor  # scale to ~0.5-1.5
                adjusted = base_weight * factor
                max_up = base_weight * (1 + self.MAX_WEIGHT_CHANGE)
                max_down = base_weight * (1 - self.MAX_WEIGHT_CHANGE)
                new_weights[agent] = max(max_down, min(max_up, adjusted))
            total += new_weights[agent]

        if total > 0:
            new_weights = {k: v / total for k, v in new_weights.items()}

        return new_weights

    def should_promote(self, old_weights: dict[str, float], new_weights: dict[str, float], oos_sharpe_delta: float) -> bool:
        """Only promote new weights if OOS Sharpe improves."""
        return oos_sharpe_delta > 0.02
