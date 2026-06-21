"""Market regime classification from indicator snapshots."""

from __future__ import annotations

from src.agents.base_agent import Regime


class RegimeDetector:
    """Classify market regime from ADX, ATR percentile, and BB width."""

    def classify(
        self,
        adx: float,
        atr_percentile: float,
        bb_width_percentile: float,
    ) -> Regime:
        if atr_percentile >= 80:
            return Regime.VOLATILE
        if atr_percentile >= 75 and adx < 25:
            return Regime.VOLATILE
        if adx >= 25:
            return Regime.TRENDING
        if adx < 20 and bb_width_percentile <= 15 and atr_percentile <= 35:
            return Regime.CALM
        return Regime.RANGING
