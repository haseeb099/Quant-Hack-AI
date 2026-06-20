"""Trend-following agent for H1/H4 timeframes."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector


class TrendSurferAgent(BaseTradingAgent):
    name = "trend_surfer"
    base_weight = 0.30

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        adx_threshold = cfg.get("adx_threshold", 25)
        base_conf = cfg.get("base_confidence", 0.60)
        max_conf = cfg.get("max_confidence", 0.95)
        stop_mult = cfg.get("stop_atr_mult", 2.0)
        target_mult = cfg.get("target_atr_mult", 3.0)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning_parts: list[str] = []

        if features.adx > adx_threshold:
            if (
                features.close > features.ema_50
                and features.ema_9 > features.ema_21
                and features.macd_histogram > 0
            ):
                direction = Direction.BUY
                confidence = base_conf
                reasoning_parts.append("Uptrend: price>EMA50, EMA9>EMA21, MACD hist>0, ADX>25")
                if features.adx > 30:
                    confidence += 0.10
                    reasoning_parts.append("Strong ADX>30")
                if features.volume_ratio > 1.5:
                    confidence += 0.10
                    reasoning_parts.append("Volume>1.5x")
                if features.ema_200 > 0:
                    dist = abs(features.close - features.ema_200) / features.ema_200
                    if dist > 0.02:
                        confidence += 0.05
                        reasoning_parts.append("Mature trend vs EMA200")
                prev_hist = features.extras.get("macd_histogram_prev", 0.0)
                if features.macd_histogram > prev_hist > 0:
                    confidence += 0.05
                    reasoning_parts.append("Accelerating MACD histogram")
            elif (
                features.close < features.ema_50
                and features.ema_9 < features.ema_21
                and features.macd_histogram < 0
            ):
                direction = Direction.SELL
                confidence = base_conf
                reasoning_parts.append("Downtrend: price<EMA50, EMA9<EMA21, MACD hist<0, ADX>25")
                if features.adx > 30:
                    confidence += 0.10
                if features.volume_ratio > 1.5:
                    confidence += 0.10
                if features.ema_200 > 0:
                    dist = abs(features.close - features.ema_200) / features.ema_200
                    if dist > 0.02:
                        confidence += 0.05
                prev_hist = features.extras.get("macd_histogram_prev", 0.0)
                if features.macd_histogram < prev_hist < 0:
                    confidence += 0.05

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
            reasoning="; ".join(reasoning_parts) or "No trend signal",
        )
