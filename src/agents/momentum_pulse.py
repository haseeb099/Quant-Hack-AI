"""Momentum continuation agent — ADX + MACD cross without squeeze requirement."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector


class MomentumPulseAgent(BaseTradingAgent):
    name = "momentum_pulse"
    base_weight = 0.15

    @staticmethod
    def _macd_bullish_cross(features: FeatureVector) -> bool:
        macd_line = features.extras.get("macd_line", 0.0)
        macd_signal = features.extras.get("macd_signal", 0.0)
        prev_hist = features.extras.get("macd_histogram_prev", 0.0)
        expanding = features.macd_histogram > prev_hist
        return macd_line > macd_signal and features.macd_histogram > 0 and prev_hist <= 0 and expanding

    @staticmethod
    def _macd_bearish_cross(features: FeatureVector) -> bool:
        macd_line = features.extras.get("macd_line", 0.0)
        macd_signal = features.extras.get("macd_signal", 0.0)
        prev_hist = features.extras.get("macd_histogram_prev", 0.0)
        expanding = features.macd_histogram < prev_hist
        return macd_line < macd_signal and features.macd_histogram < 0 and prev_hist >= 0 and expanding

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        adx_threshold = cfg.get("adx_threshold", 25)
        vol_threshold = cfg.get("volume_threshold", 1.2)
        base_conf = cfg.get("base_confidence", 0.55)
        max_conf = cfg.get("max_confidence", 0.80)
        stop_mult = cfg.get("stop_atr_mult", 1.8)
        target_mult = cfg.get("target_atr_mult", 2.5)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning = "No momentum signal"

        if features.adx <= adx_threshold or features.volume_ratio < vol_threshold:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="ADX or volume below threshold",
            )

        if features.bb_width_percentile <= 5:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="BB squeeze present — momentum agent skips",
            )

        transition_penalty = 1.0
        if 25 <= features.adx <= 28:
            transition_penalty = 0.5
            reasoning = "ADX transition zone 25-28 — reduced confidence"

        if self._macd_bullish_cross(features) and features.ema_9 > features.ema_21:
            direction = Direction.BUY
            confidence = (base_conf + 0.05) * transition_penalty
            reasoning = "Bullish momentum: ADX>25, MACD cross up with expanding histogram"
        elif self._macd_bearish_cross(features) and features.ema_9 < features.ema_21:
            direction = Direction.SELL
            confidence = (base_conf + 0.05) * transition_penalty
            reasoning = "Bearish momentum: ADX>25, MACD cross down with expanding histogram"

        confidence = self._clamp_confidence(confidence, 0.0, max_conf)
        stop = target = None
        if direction == Direction.BUY:
            stop = features.close - features.atr_14 * stop_mult
            target = features.close + features.atr_14 * target_mult
        elif direction == Direction.SELL:
            stop = features.close + features.atr_14 * stop_mult
            target = features.close - features.atr_14 * target_mult

        return AgentSignal(
            agent_name=self.name,
            symbol=features.symbol,
            direction=direction,
            confidence=confidence,
            stop_loss=stop,
            take_profit=target,
            reasoning=reasoning,
        )
