"""Half-Kelly position sizing with volatility adjustment."""

from __future__ import annotations

from typing import Any


class KellySizer:
    """Computes position size using Half-Kelly with volatility and confidence scaling."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def compute_size(
        self,
        equity: float,
        win_rate: float,
        reward_risk_ratio: float,
        atr_14: float,
        atr_50: float,
        confidence: float,
        phase_multiplier: float = 1.0,
        drawdown_multiplier: float = 1.0,
        orchestrator_scale: float = 1.0,
    ) -> float:
        kelly_pct = self._half_kelly(win_rate, reward_risk_ratio)
        vol_adj = 1.0 / (1.0 + atr_14 / (atr_50 + 1e-9))
        conf_scale = 0.7 + (confidence * 0.3)  # 0.7 at conf=0, 1.0 at conf=1

        raw = equity * kelly_pct * vol_adj * conf_scale
        raw *= phase_multiplier * drawdown_multiplier * orchestrator_scale

        max_risk = equity * self.config.get("max_risk_per_trade", 0.02)
        return min(raw, max_risk)

    @staticmethod
    def _half_kelly(win_rate: float, reward_risk: float) -> float:
        if reward_risk <= 0:
            return 0.0
        full_kelly = win_rate - (1 - win_rate) / reward_risk
        return max(0.0, full_kelly * 0.5)
