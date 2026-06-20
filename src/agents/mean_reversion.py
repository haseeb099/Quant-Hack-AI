"""Mean-reversion agent for ranging forex markets."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector


class MeanReversionAgent(BaseTradingAgent):
    name = "mean_reversion"
    base_weight = 0.20

    @staticmethod
    def _near_lower_band(features: FeatureVector, proximity_pct: float) -> bool:
        bb_lower = features.extras.get("bb_lower")
        if bb_lower is None:
            return False
        band_range = features.extras.get("bb_upper", features.close) - bb_lower
        if band_range <= 0:
            return features.close <= bb_lower
        proximity = (features.close - bb_lower) / band_range
        return proximity <= proximity_pct / 100.0

    @staticmethod
    def _near_upper_band(features: FeatureVector, proximity_pct: float) -> bool:
        bb_upper = features.extras.get("bb_upper")
        if bb_upper is None:
            return False
        bb_lower = features.extras.get("bb_lower", features.close)
        band_range = bb_upper - bb_lower
        if band_range <= 0:
            return features.close >= bb_upper
        proximity = (bb_upper - features.close) / band_range
        return proximity <= proximity_pct / 100.0

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        rsi_oversold = cfg.get("rsi_oversold", 30)
        rsi_overbought = cfg.get("rsi_overbought", 70)
        adx_max = cfg.get("adx_max", 25)
        min_conf = cfg.get("min_confidence", 0.70)
        max_conf = cfg.get("max_confidence", 0.90)
        proximity_pct = cfg.get("bb_proximity_pct", 5)
        stop_mult = cfg.get("stop_atr_mult", 1.0)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning_parts: list[str] = []

        if features.adx >= adx_max:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="ADX too high for mean reversion",
            )

        if features.rsi_14 < rsi_oversold and self._near_lower_band(features, proximity_pct):
            direction = Direction.BUY
            confidence = min_conf
            reasoning_parts.append(f"RSI oversold ({features.rsi_14:.1f}) at lower BB")
            if features.rsi_14 < 20:
                confidence += 0.10
                reasoning_parts.append("Deep oversold RSI<20")
        elif features.rsi_14 > rsi_overbought and self._near_upper_band(features, proximity_pct):
            direction = Direction.SELL
            confidence = min_conf
            reasoning_parts.append(f"RSI overbought ({features.rsi_14:.1f}) at upper BB")
            if features.rsi_14 > 80:
                confidence += 0.10
                reasoning_parts.append("Deep overbought RSI>80")

        confidence = self._clamp_confidence(confidence, 0.0, max_conf)
        stop = target = None
        if direction == Direction.BUY:
            stop = features.close - features.atr_14 * stop_mult
            target = features.extras.get("bb_middle", features.close)
        elif direction == Direction.SELL:
            stop = features.close + features.atr_14 * stop_mult
            target = features.extras.get("bb_middle", features.close)

        return AgentSignal(
            agent_name=self.name,
            symbol=features.symbol,
            direction=direction,
            confidence=confidence,
            stop_loss=stop,
            take_profit=target,
            reasoning="; ".join(reasoning_parts) or "No mean-reversion signal",
        )
