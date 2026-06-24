"""Bounded offline parameter optimizer — allowed knobs only."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import yaml

from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory

logger = logging.getLogger(__name__)

TUNABLE_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "trend_surfer": {
        "adx_threshold": (-3, 3),
        "pullback_atr_mult": (-0.2, 0.2),
    },
    "breakout_hunter": {
        "donchian_period": (-2, 2),
        "bb_squeeze_percentile": (-3, 3),
    },
    "momentum_pulse": {
        "adx_threshold": (-3, 3),
        "volume_threshold": (-0.1, 0.1),
    },
    "mean_reversion": {
        "rsi_oversold": (-5, 5),
        "rsi_overbought": (-5, 5),
        "adx_max": (-4, 4),
    },
    "sentiment_agent": {
        "min_score": (-0.05, 0.05),
        "min_confidence": (-0.05, 0.05),
    },
    "ml_signal": {
        "min_confidence": (-0.05, 0.05),
    },
}


def _clamp_delta(base: float, delta: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    delta = max(lo, min(hi, delta))
    return base + delta


class ParameterOptimizer:
    """Grid search on bounded agent parameters using trade memory performance."""

    def __init__(
        self,
        config: QuantAIConfig | None = None,
        memory: LayeredMemory | None = None,
    ) -> None:
        self.config = config or QuantAIConfig.load()
        self.memory = memory or LayeredMemory()

    def _score_agent(self, agent: str, overrides: dict[str, float]) -> float:
        perf = self.memory.agent_performance(agent)
        attr = self.memory.agent_vote_attribution(agent)
        wr = perf.get("win_rate")
        attr_wr = attr.get("win_rate")
        avg_r = perf.get("avg_r") or 0.0
        samples = perf.get("sample_size") or 0
        if samples < 5:
            return 0.0
        blended_wr = 0.6 * (wr or 0.5) + 0.4 * (attr_wr or wr or 0.5)
        penalty = max(0, 5 - samples) * 0.02
        return blended_wr * 0.5 + avg_r * 0.3 - penalty

    def optimize(self) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
        """Return (tuned_agents_config, parameter_deltas)."""
        base_agents = deepcopy(self.config.agents)
        tuned = deepcopy(base_agents)
        deltas: dict[str, dict[str, float]] = {}

        for agent, param_bounds in TUNABLE_BOUNDS.items():
            if agent not in base_agents:
                continue
            best_score = self._score_agent(agent, {})
            best_overrides: dict[str, float] = {}
            agent_cfg = base_agents[agent]

            for param, (lo, hi) in param_bounds.items():
                base_val = float(agent_cfg.get(param, 0))
                candidates = [lo, 0, hi]
                for delta in candidates:
                    new_val = _clamp_delta(base_val, delta, (lo, hi))
                    trial = {param: new_val}
                    score = self._score_agent(agent, trial)
                    if score >= best_score:
                        best_score = score
                        best_overrides[param] = new_val

            agent_deltas: dict[str, float] = {}
            for param, new_val in best_overrides.items():
                old_val = float(agent_cfg.get(param, new_val))
                if abs(new_val - old_val) > 1e-9:
                    tuned[agent][param] = new_val
                    agent_deltas[param] = round(new_val - old_val, 4)
            if agent_deltas:
                deltas[agent] = agent_deltas

        return tuned, deltas

    def write_tuned_yaml(
        self,
        tuned_agents: dict[str, dict[str, Any]],
        regime_boosts: dict[str, dict[str, float]] | None = None,
        path: str = "data/agents_tuned.yaml",
    ) -> None:
        payload = {
            "agents": tuned_agents,
            "regime_boosts": regime_boosts or self.config.regime_boosts,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(payload, f, default_flow_style=False, sort_keys=False)
        logger.info("Wrote tuned agent config to %s", path)
