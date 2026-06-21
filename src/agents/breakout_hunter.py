"""Volatility breakout agent for M15/H1 timeframes."""

from __future__ import annotations

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector


class BreakoutHunterAgent(BaseTradingAgent):
    name = "breakout_hunter"
    base_weight = 0.30

    def analyze(self, features: FeatureVector) -> AgentSignal:
        cfg = self.config
        squeeze_pct = cfg.get("bb_squeeze_percentile", 5)
        min_squeeze_bars = cfg.get("min_squeeze_bars", 8)
        vol_threshold = cfg.get("volume_spike_threshold", 1.5)
        rsi_long = cfg.get("rsi_filter_long", 75)
        rsi_short = cfg.get("rsi_filter_short", 25)
        base_conf = cfg.get("base_confidence", 0.65)
        max_conf = cfg.get("max_confidence", 0.90)
        stop_mult = cfg.get("stop_atr_mult", 1.5)
        target_mult = cfg.get("target_atr_mult", 3.0)

        direction = Direction.HOLD
        confidence = 0.0
        reasoning_parts: list[str] = []

        session = features.extras.get("session_name", "")
        is_crypto = features.symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        if is_crypto and session not in ("london", "ny", "overlap", ""):
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="Crypto breakout gated to London/NY/overlap sessions",
            )

        is_squeeze = features.bb_width_percentile <= squeeze_pct
        squeeze_bars = int(features.extras.get("bb_squeeze_bars", 0))
        vol_confirmed = features.volume_ratio >= vol_threshold

        if not (is_squeeze and vol_confirmed):
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="No breakout: requires BB squeeze + volume spike",
            )

        if squeeze_bars < min_squeeze_bars:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"Squeeze duration {squeeze_bars} bars < {min_squeeze_bars} required",
            )

        donchian_high_prev = features.extras.get("donchian_high_prev", features.donchian_high)
        donchian_low_prev = features.extras.get("donchian_low_prev", features.donchian_low)
        retest_long = (
            features.close > features.donchian_high
            and features.close <= donchian_high_prev * 1.002
        )
        retest_short = (
            features.close < features.donchian_low
            and features.close >= donchian_low_prev * 0.998
        )
        first_pierce_long = features.close > features.donchian_high and not retest_long
        first_pierce_short = features.close < features.donchian_low and not retest_short

        if retest_long and features.rsi_14 < rsi_long:
            direction = Direction.BUY
            confidence = base_conf + 0.10
            reasoning_parts.append("Retest of Donchian high after squeeze breakout")
        elif retest_short and features.rsi_14 > rsi_short:
            direction = Direction.SELL
            confidence = base_conf + 0.10
            reasoning_parts.append("Retest of Donchian low after squeeze breakdown")
        elif first_pierce_long or first_pierce_short:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="First pierce without retest — waiting for retest entry",
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
            reasoning="; ".join(reasoning_parts) or "No breakout signal",
        )
