"""Trend-following agent for H1/H4 timeframes."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector, Regime


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
        pullback_mult = cfg.get("pullback_atr_mult", 1.5)
        require_mtf = cfg.get("require_mtf_alignment", True)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning_parts: list[str] = []

        h1_bull = features.extras.get("h1_trend_bull")
        h1_bear = features.extras.get("h1_trend_bear")
        h4_bull = features.extras.get("h4_trend_bull")
        h4_bear = features.extras.get("h4_trend_bear")
        if require_mtf and h1_bull is not None and h4_bull is not None:
            if not (h1_bull and h4_bull) and not (h1_bear and h4_bear):
                return AgentSignal(
                    agent_name=self.name,
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    reasoning="MTF misalignment — H1/H4 trends not aligned",
                )
        elif h1_bull is not None or h4_bull is not None:
            bull_ok = (h1_bull is True or h4_bull is True)
            bear_ok = (h1_bear is True or h4_bear is True)
            if not bull_ok and not bear_ok:
                return AgentSignal(
                    agent_name=self.name,
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    reasoning="Higher timeframe bias unclear",
                )

        volatile_mode = features.regime in (Regime.VOLATILE, Regime.TRENDING)
        trending_mode = features.regime == Regime.TRENDING
        effective_adx = adx_threshold - (3 if volatile_mode else 0)

        if features.adx > effective_adx:
            pullback_window = features.atr_14 * pullback_mult
            if volatile_mode:
                pullback_window = features.atr_14 * (pullback_mult + 0.5)

            if (
                features.close > features.ema_50
                and features.ema_9 > features.ema_21
                and features.macd_histogram > 0
            ):
                near_ema = abs(features.close - features.ema_21) <= pullback_window
                momentum_entry = (
                    features.adx > effective_adx + 5
                    and (volatile_mode or trending_mode)
                )
                if not near_ema and not momentum_entry:
                    return AgentSignal(
                        agent_name=self.name,
                        symbol=features.symbol,
                        direction=Direction.HOLD,
                        confidence=0.0,
                        reasoning="Uptrend without pullback or momentum continuation",
                    )
                direction = Direction.BUY
                confidence = base_conf
                reasoning_parts.append("Uptrend: EMA stack bullish with ADX confirmation")
                if near_ema:
                    reasoning_parts.append("Pullback to EMA21 zone")
                if momentum_entry and not near_ema:
                    reasoning_parts.append("Volatile momentum continuation")
                if features.adx > 30:
                    confidence += 0.10
                    reasoning_parts.append("Strong ADX>30")
                if features.volume_ratio > 1.2:
                    confidence += 0.08
                    reasoning_parts.append("Volume>1.2x")
                if features.ema_200 > 0:
                    dist = abs(features.close - features.ema_200) / features.ema_200
                    if dist > 0.015:
                        confidence += 0.05
                        reasoning_parts.append("Trend vs EMA200")
                prev_hist = features.extras.get("macd_histogram_prev", 0.0)
                if features.macd_histogram > prev_hist > 0:
                    confidence += 0.05
                    reasoning_parts.append("Accelerating MACD histogram")
            elif (
                features.close < features.ema_50
                and features.ema_9 < features.ema_21
                and features.macd_histogram < 0
            ):
                near_ema = abs(features.close - features.ema_21) <= pullback_window
                momentum_entry = (
                    features.adx > effective_adx + 5
                    and (volatile_mode or trending_mode)
                )
                if not near_ema and not momentum_entry:
                    return AgentSignal(
                        agent_name=self.name,
                        symbol=features.symbol,
                        direction=Direction.HOLD,
                        confidence=0.0,
                        reasoning="Downtrend without pullback or momentum continuation",
                    )
                direction = Direction.SELL
                confidence = base_conf
                reasoning_parts.append("Downtrend: EMA stack bearish with ADX confirmation")
                if near_ema:
                    reasoning_parts.append("Pullback to EMA21 zone")
                if momentum_entry and not near_ema:
                    reasoning_parts.append("Volatile momentum continuation")
                if features.adx > 30:
                    confidence += 0.10
                if features.volume_ratio > 1.2:
                    confidence += 0.08
                if features.ema_200 > 0:
                    dist = abs(features.close - features.ema_200) / features.ema_200
                    if dist > 0.015:
                        confidence += 0.05
                prev_hist = features.extras.get("macd_histogram_prev", 0.0)
                if features.macd_histogram < prev_hist < 0:
                    confidence += 0.05

        if direction == Direction.SELL and features.rsi_14 < 32:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"RSI {features.rsi_14:.1f} oversold — trend short deferred",
            )
        if direction == Direction.BUY and features.rsi_14 > 68:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"RSI {features.rsi_14:.1f} overbought — trend long deferred",
            )

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
