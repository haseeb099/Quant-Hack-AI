"""Sentiment agent — news and macro-driven trading signals."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector, Regime


class SentimentAgent(BaseTradingAgent):
    name = "sentiment_agent"
    base_weight = 0.10

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        min_score = float(cfg.get("min_score", 0.4))
        min_conf = float(cfg.get("min_confidence", 0.70))
        max_conf = float(cfg.get("max_confidence", 0.85))
        stop_mult = float(cfg.get("stop_atr_mult", 1.5))
        target_mult = float(cfg.get("target_atr_mult", 2.5))

        snapshot = features.extras.get("sentiment_snapshot")
        event_gate = features.extras.get("event_gate", {})
        macro = features.extras.get("macro_regime", {})

        if not snapshot:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="No sentiment snapshot available",
            )

        score = float(snapshot.get("score", 0.0))
        confidence = float(snapshot.get("confidence", 0.0))
        headline_count = int(snapshot.get("headline_count", 0))
        macro_bias = snapshot.get("macro_bias", macro.get("bias", "neutral"))

        if not event_gate.get("allowed", True):
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"Event gate blocked: {event_gate.get('reason', '')}",
            )

        if headline_count < 2 or confidence < min_conf:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"Insufficient sentiment confidence ({confidence:.2f}) or headlines ({headline_count})",
            )

        direction = Direction.HOLD
        reasoning = snapshot.get("summary", "Neutral sentiment")

        is_crypto = features.symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        is_metal = features.symbol in {"XAU/USD", "XAG/USD"}

        if score > min_score:
            direction = Direction.BUY
            reasoning = f"Bullish sentiment {score:.2f}: {reasoning}"
            if macro_bias == "risk_off" and is_crypto:
                confidence *= 0.72
                reasoning += "; macro risk-off strongly penalizes crypto long"
            if macro_bias == "risk_off" and is_metal:
                confidence = min(confidence * 1.1, max_conf)
                reasoning += "; safe-haven boost for metals"
        elif score < -min_score:
            direction = Direction.SELL
            reasoning = f"Bearish sentiment {score:.2f}: {reasoning}"
            if macro_bias == "risk_on" and is_crypto:
                confidence *= 0.8
                reasoning += "; macro risk-on reduces bearish crypto conviction"

        if features.regime == Regime.RANGING and abs(score) < 0.55:
            confidence *= 0.7
            reasoning += "; ranging regime — reduced sentiment weight"

        confidence = self._clamp_confidence(confidence, 0.0, max_conf)
        if direction == Direction.HOLD:
            confidence = 0.0

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
            metadata={"sentiment_score": score, "macro_bias": macro_bias},
        )
