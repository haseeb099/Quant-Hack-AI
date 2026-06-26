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
        allocation_cap: float | None = None,
        leverage_haircut: float = 1.0,
        margin_size_multiplier: float = 1.0,
        max_risk_override: float | None = None,
        competition_mode: bool = False,
        competition_mode_boost: float = 1.4,
    ) -> float:
        kelly_fraction = 0.65 if competition_mode else 0.5
        kelly_pct = self._kelly_fraction(win_rate, reward_risk_ratio, kelly_fraction)
        vol_adj = 1.0 / (1.0 + atr_14 / (atr_50 + 1e-9))
        conf_scale = 0.82 + (confidence * 0.28)  # 0.82 at conf=0, 1.10 at conf=1

        raw = equity * kelly_pct * vol_adj * conf_scale
        raw *= phase_multiplier * drawdown_multiplier * orchestrator_scale
        raw *= leverage_haircut * margin_size_multiplier
        if competition_mode:
            raw *= competition_mode_boost

        max_risk_pct = max_risk_override or self.config.get("max_risk_per_trade", 0.02)
        max_risk = equity * max_risk_pct
        if allocation_cap is not None:
            max_risk = min(max_risk, equity * allocation_cap)
        return min(raw, max_risk)

    @staticmethod
    def _kelly_fraction(win_rate: float, reward_risk: float, fraction: float = 0.5) -> float:
        if reward_risk <= 0:
            return 0.0
        full_kelly = win_rate - (1 - win_rate) / reward_risk
        return max(0.0, full_kelly * fraction)

    @staticmethod
    def _half_kelly(win_rate: float, reward_risk: float) -> float:
        return KellySizer._kelly_fraction(win_rate, reward_risk, 0.5)
