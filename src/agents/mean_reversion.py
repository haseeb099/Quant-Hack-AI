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

    @staticmethod
    def _has_bullish_divergence(features: FeatureVector) -> bool:
        rsi_prev = features.extras.get("rsi_prev", features.rsi_14)
        return features.rsi_14 > rsi_prev and features.rsi_14 < 35

    @staticmethod
    def _has_bearish_divergence(features: FeatureVector) -> bool:
        rsi_prev = features.extras.get("rsi_prev", features.rsi_14)
        return features.rsi_14 < rsi_prev and features.rsi_14 > 65

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        rsi_oversold = cfg.get("rsi_oversold", 30)
        rsi_overbought = cfg.get("rsi_overbought", 70)
        adx_max = cfg.get("adx_max", 25)
        h1_adx_max = cfg.get("h1_adx_max", 22)
        min_conf = cfg.get("min_confidence", 0.70)
        max_conf = cfg.get("max_confidence", 0.90)
        proximity_pct = cfg.get("bb_proximity_pct", 5)
        stop_mult = cfg.get("stop_atr_mult", 1.0)
        require_divergence = cfg.get("require_divergence", True)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning_parts: list[str] = []

        is_metal = features.symbol in {"XAU/USD", "XAG/USD"}
        macro = features.extras.get("macro_regime") or {}
        macro_bias = macro.get("bias", "neutral")

        h1_adx = features.extras.get("h1_adx")
        if h1_adx is not None and h1_adx > h1_adx_max:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"H1 ADX {h1_adx:.1f} > {h1_adx_max} — block mean reversion",
            )

        if features.adx >= adx_max:
            if not (
                is_metal
                and macro_bias == "risk_off"
                and features.rsi_14 < 32
            ):
                return AgentSignal(
                    agent_name=self.name,
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    reasoning="ADX too high for mean reversion",
                )

        instrument_bias = str(features.extras.get("instrument_bias", "mixed"))

        vol_declining = features.volume_ratio < features.extras.get("volume_prev_ratio", features.volume_ratio)

        if features.rsi_14 < rsi_oversold and self._near_lower_band(features, proximity_pct):
            extreme = features.rsi_14 < 28
            confirm = (
                self._has_bullish_divergence(features)
                or vol_declining
                or extreme
                or not require_divergence
            )
            if not confirm:
                return AgentSignal(
                    agent_name=self.name,
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    reasoning="Oversold but no confirmation",
                )
            direction = Direction.BUY
            confidence = min_conf
            reasoning_parts.append(f"RSI oversold ({features.rsi_14:.1f}) at lower BB")
            if features.rsi_14 < 22:
                confidence += 0.12
                reasoning_parts.append("Deep oversold RSI<22")
            elif features.rsi_14 < 28:
                confidence += 0.06
        elif features.rsi_14 > rsi_overbought and self._near_upper_band(features, proximity_pct):
            extreme = features.rsi_14 > 72
            confirm = (
                self._has_bearish_divergence(features)
                or vol_declining
                or extreme
                or not require_divergence
            )
            if not confirm:
                return AgentSignal(
                    agent_name=self.name,
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    reasoning="Overbought but no confirmation",
                )
            direction = Direction.SELL
            confidence = min_conf
            reasoning_parts.append(f"RSI overbought ({features.rsi_14:.1f}) at upper BB")
            if features.rsi_14 > 78:
                confidence += 0.12
                reasoning_parts.append("Deep overbought RSI>78")
            elif features.rsi_14 > 72:
                confidence += 0.06

        if direction == Direction.SELL and is_metal and macro_bias == "risk_off":
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="Metals MR SELL suppressed — risk-off safe-haven uptrend risk",
            )
        if direction == Direction.SELL and is_metal and instrument_bias == "bullish":
            confidence = min(confidence, 0.55)
            reasoning_parts.append("Bullish metal bias caps MR SELL confidence")

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
