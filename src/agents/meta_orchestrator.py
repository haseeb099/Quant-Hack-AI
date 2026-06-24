"""Meta-orchestrator — Claude-powered with rule-based fallback."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from src.agents.base_agent import AgentSignal, Direction, FeatureVector, Regime

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorDecision:
    symbol: str
    direction: Direction
    confidence: float
    size_scale: float
    reasoning: str
    risk_assessment: str = ""
    urgency: str = "normal"
    agent_votes: list[AgentSignal] | None = None
    used_ai: bool = False
    skip_reason: str | None = None


class MetaOrchestrator:
    """Aggregates agent signals into a final trading decision.

    Uses Claude when available; falls back to regime-weighted voting.
    """

    def __init__(
        self,
        config: dict[str, Any],
        regime_boosts: dict[str, dict[str, float]],
        agent_weights: dict[str, float] | None = None,
        agent_best_regimes: dict[str, list[str]] | None = None,
    ) -> None:
        self.config = config
        self.regime_boosts = regime_boosts
        self.agent_weights = agent_weights or config.get("agent_weights", {})
        self.agent_best_regimes = agent_best_regimes or config.get("agent_best_regimes", {})
        self._anthropic_model_override = os.getenv("META_ORCHESTRATOR_MODEL", "").strip()
        self._anthropic_config_model = (
            config.get("anthropic_model")
            or config.get("model")
        )
        has_ai = self._has_pydantic_ai()
        from src.utils.llm_providers import has_llm_providers

        self._use_ai = has_llm_providers("orchestrator") and has_ai
        cooldown_env = os.getenv("META_ORCHESTRATOR_COOLDOWN_MINUTES", "").strip()
        self._cooldown_minutes = float(cooldown_env) if cooldown_env else config.get("cooldown_minutes", 5)
        self._last_ai_call: dict[str, float] = {}

    @staticmethod
    def _has_pydantic_ai() -> bool:
        try:
            import pydantic_ai  # noqa: F401
            return True
        except ImportError:
            return False

    def _min_confidence(self) -> float:
        return float(
            os.getenv(
                "QUANTAI_MIN_CONFIDENCE",
                self.config.get("min_agent_confidence", 0.65),
            )
        )

    @staticmethod
    def _cap_confidence_from_agents(
        direction: Direction,
        confidence: float,
        signals: list[AgentSignal],
        *,
        max_boost: float = 0.08,
    ) -> float:
        """Prevent orchestrator confidence from exceeding agent evidence."""
        if direction == Direction.HOLD or confidence <= 0:
            return confidence
        agreeing = [
            s for s in signals
            if s.is_actionable and s.direction == direction
        ]
        if not agreeing:
            return min(confidence, 0.70)
        ceiling = max(s.confidence for s in agreeing) + max_boost
        return min(confidence, ceiling)

    def _finalize_decision(
        self,
        decision: OrchestratorDecision,
        signals: list[AgentSignal],
    ) -> OrchestratorDecision:
        if decision.direction == Direction.HOLD:
            return decision
        capped = self._cap_confidence_from_agents(
            decision.direction, decision.confidence, signals,
        )
        if capped + 1e-9 < decision.confidence:
            decision.confidence = capped
            decision.reasoning = (
                f"{decision.reasoning}; confidence capped to agent ceiling {capped:.2f}"
            )
        return decision

    def decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        drawdown_tier: str = "normal",
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        actionable = [s for s in signals if s.is_actionable]
        min_conf = self._min_confidence()

        if not actionable or max(s.confidence for s in actionable) < min_conf:
            debate_decision = self._debate_fallback_decision(features, signals, context, min_conf)
            if debate_decision is not None:
                return self._finalize_decision(debate_decision, signals)
            return OrchestratorDecision(
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                size_scale=0.0,
                reasoning="No agent above minimum confidence threshold",
                agent_votes=signals,
            )

        if drawdown_tier in ("critical", "emergency"):
            return OrchestratorDecision(
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                size_scale=0.0,
                reasoning=f"Drawdown tier {drawdown_tier} — no new trades",
                agent_votes=signals,
            )

        decision: OrchestratorDecision | None = None
        skip_reason: str | None = None
        if self._use_ai and not self._can_call_ai(features.symbol):
            skip_reason = "cooldown"
        elif self._use_ai and not self._signals_need_ai(actionable):
            skip_reason = "agent_consensus"
        elif self._use_ai and self._can_call_ai(features.symbol):
            try:
                decision = self._ai_decide(features, actionable, context)
            except Exception as exc:
                logger.warning(
                    "AI decision failed for %s after provider fallback, using rule-based: %s: %s",
                    features.symbol,
                    type(exc).__name__,
                    exc,
                )

        if decision is None:
            decision = self._rule_based_decide(features, actionable, context)
            if not decision.used_ai and skip_reason:
                decision.skip_reason = skip_reason

        if decision.direction == Direction.HOLD:
            debate_decision = self._debate_fallback_decision(features, signals, context, min_conf)
            if debate_decision is not None:
                return self._finalize_decision(debate_decision, signals)

        return self._finalize_decision(decision, signals)

    def _can_call_ai(self, symbol: str) -> bool:
        now = time.time()
        last = self._last_ai_call.get(symbol, 0)
        return (now - last) >= self._cooldown_minutes * 60

    def _signals_need_ai(self, signals: list[AgentSignal]) -> bool:
        from src.utils.llm_providers import orchestrator_ai_on_conflict_only

        if not orchestrator_ai_on_conflict_only():
            return True
        if not signals:
            return False

        trade_dirs = {s.direction for s in signals if s.direction != Direction.HOLD}
        if len(trade_dirs) > 1:
            return True

        confidences = [s.confidence for s in signals]
        spread = max(confidences) - min(confidences)
        if spread > 0.12:
            return True

        if len(trade_dirs) == 1 and max(confidences) >= self._min_confidence() and spread <= 0.12:
            return False

        return len(signals) <= 1 or max(confidences) < self._min_confidence() + 0.08

    def _debate_fallback_decision(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None,
        min_conf: float,
    ) -> OrchestratorDecision | None:
        """When individual agents are cautious, allow strong bull/bear debate to enter."""
        if not context:
            return None
        winner = context.get("debate_winner")
        debate_conf = float(context.get("debate_confidence") or 0)
        if winner not in ("bull", "bear") or debate_conf < min_conf * 0.88:
            return None
        direction = Direction.BUY if winner == "bull" else Direction.SELL
        synthesis = context.get("debate_synthesis") or context.get("debate", {}).get("synthesis", "")
        return OrchestratorDecision(
            symbol=features.symbol,
            direction=direction,
            confidence=min(debate_conf, 0.92),
            size_scale=0.85,
            reasoning=f"Debate-driven {direction.value} ({winner} {debate_conf:.2f}) — {synthesis}",
            risk_assessment=f"Regime: {features.regime.value}",
            agent_votes=signals,
            used_ai=False,
        )

    def _rule_based_decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        regime_key = features.regime.value
        boosts = self.regime_boosts.get(regime_key, {})
        min_conf = self._min_confidence()
        return_focus = bool(context and context.get("return_focus"))

        buy_strengths: list[float] = []
        sell_strengths: list[float] = []
        buy_score = 0.0
        sell_score = 0.0
        backtest_rates = (context or {}).get("backtest_agent_win_rates") or {}
        audit_rates = (context or {}).get("audit_agent_win_rates") or {}
        symbol_rates = (context or {}).get("symbol_agent_win_rates") or {}
        for signal in signals:
            strength = self._signal_strength(
                signal, boosts, regime_key, backtest_rates, audit_rates, symbol_rates,
            )
            weight = self.agent_weights.get(signal.agent_name, 1.0)
            if signal.direction == Direction.BUY:
                buy_strengths.append(strength)
                buy_score += strength * (0.45 + weight)
            elif signal.direction == Direction.SELL:
                sell_strengths.append(strength)
                sell_score += strength * (0.45 + weight)

        best_buy = max(buy_strengths) if buy_strengths else 0.0
        best_sell = max(sell_strengths) if sell_strengths else 0.0

        if buy_score > sell_score and (best_buy > 0 or buy_score > 0):
            direction = Direction.BUY
            confidence = min(best_buy, 0.92)
            reasoning = f"Regime-weighted BUY ({regime_key}): best={best_buy:.2f} ensemble={buy_score:.2f}"
        elif sell_score > buy_score and (best_sell > 0 or sell_score > 0):
            direction = Direction.SELL
            confidence = min(best_sell, 0.92)
            reasoning = f"Regime-weighted SELL ({regime_key}): best={best_sell:.2f} ensemble={sell_score:.2f}"
        else:
            direction = Direction.HOLD
            confidence = 0.0
            reasoning = "Conflicting signals — holding"

        directions = {s.direction for s in signals if s.is_actionable}
        size_scale = 0.85 if len(directions) > 1 else 1.0
        if return_focus and direction != Direction.HOLD:
            size_scale = max(size_scale, float(context.get("min_orchestrator_size_scale", 0.90) if context else 0.90))

        if context and context.get("semantic_best_agent"):
            best = context["semantic_best_agent"]
            for sig in signals:
                if sig.agent_name == best and sig.is_actionable:
                    confidence = min(confidence * 1.05, 1.0)
                    reasoning += f"; semantic boost for {best}"

        if context and context.get("debate_winner") in ("bull", "bear"):
            debate_dir = Direction.BUY if context["debate_winner"] == "bull" else Direction.SELL
            debate_conf = context.get("debate_confidence", 0)
            if debate_conf >= min_conf and debate_dir == direction:
                confidence = min(max(confidence, debate_conf), 1.0)
                reasoning += f"; debate confirms {context['debate_winner']}"
            elif debate_conf >= min_conf and direction != Direction.HOLD and debate_dir != direction:
                size_scale *= 0.6
                reasoning += "; debate conflicts — reduced size"

        if context and context.get("sentiment_snapshot"):
            snap = context["sentiment_snapshot"]
            sent_score = float(snap.get("score", 0))
            if sent_score > 0.4 and direction == Direction.BUY:
                confidence = min(confidence * 1.05, 1.0)
                reasoning += "; sentiment confirms BUY"
            elif sent_score < -0.4 and direction == Direction.SELL:
                confidence = min(confidence * 1.05, 1.0)
                reasoning += "; sentiment confirms SELL"
            elif abs(sent_score) > 0.4 and direction != Direction.HOLD:
                if (sent_score > 0 and direction == Direction.SELL) or (sent_score < 0 and direction == Direction.BUY):
                    size_scale *= 0.8
                    reasoning += "; sentiment conflicts — reduced size"

        macro_conf, macro_scale, macro_note = self._apply_macro_alignment(
            features.symbol, direction, confidence, size_scale, context, adx=features.adx,
        )
        confidence, size_scale = macro_conf, macro_scale
        if macro_note:
            reasoning += macro_note

        agreeing = [
            s for s in signals
            if s.is_actionable and s.direction == direction
        ]
        if direction != Direction.HOLD and len(agreeing) >= 2:
            avg_wr = self._average_audit_win_rate(agreeing, symbol_rates, audit_rates)
            confidence = min(confidence * (1.10 if avg_wr >= 0.55 else 1.05), 1.0)
            size_scale = min(size_scale * (1.20 if avg_wr >= 0.60 else 1.12), 1.45)
            reasoning += f"; {len(agreeing)}-agent consensus"
            if avg_wr >= 0.55:
                reasoning += f" (audit WR {avg_wr:.0%})"
        elif direction != Direction.HOLD and len(agreeing) == 1 and return_focus:
            solo = agreeing[0]
            solo_wr = symbol_rates.get(solo.agent_name) or audit_rates.get(solo.agent_name)
            weak_solo_agents = {"momentum_pulse", "sentiment_agent", "mean_reversion"}
            if solo.agent_name in weak_solo_agents and solo.confidence < 0.62:
                return OrchestratorDecision(
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    size_scale=0.0,
                    reasoning=(
                        f"Solo {solo.agent_name} at {solo.confidence:.2f} — "
                        "needs trend_surfer or ML partner"
                    ),
                    agent_votes=signals,
                )
            if solo_wr is not None and solo_wr < 0.42 and confidence < 0.72:
                return OrchestratorDecision(
                    symbol=features.symbol,
                    direction=Direction.HOLD,
                    confidence=0.0,
                    size_scale=0.0,
                    reasoning=(
                        f"Solo {solo.agent_name} WR {solo_wr:.0%} too low for single-agent entry"
                    ),
                    agent_votes=signals,
                )
            if solo_wr is not None and solo_wr >= 0.60:
                size_scale = min(size_scale * 1.10, 1.40)
                reasoning += f"; proven {solo.agent_name} on symbol ({solo_wr:.0%} WR)"

        tier = (context or {}).get("symbol_tier", "B")
        if direction != Direction.HOLD and tier == "A" and confidence >= 0.62:
            size_scale = min(size_scale * 1.08, 1.45)

        effective_min = min_conf * (0.90 if return_focus else 1.0)
        if direction != Direction.HOLD and confidence < effective_min:
            return OrchestratorDecision(
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                size_scale=0.0,
                reasoning=f"Score {confidence:.2f} below minimum {effective_min:.2f}",
                agent_votes=signals,
            )

        return OrchestratorDecision(
            symbol=features.symbol,
            direction=direction,
            confidence=confidence,
            size_scale=size_scale,
            reasoning=reasoning,
            risk_assessment=f"Regime: {regime_key}",
            agent_votes=signals,
        )

    def _regime_match_multiplier(self, agent_name: str, regime_key: str) -> float:
        best = self.agent_best_regimes.get(agent_name, [])
        if not best:
            return 1.0
        if regime_key in best:
            return 1.0
        return float(self.config.get("regime_mismatch_penalty", 0.72))

    @staticmethod
    def _average_audit_win_rate(
        signals: list[AgentSignal],
        symbol_rates: dict[str, float],
        audit_rates: dict[str, float],
    ) -> float:
        values: list[float] = []
        for sig in signals:
            wr = symbol_rates.get(sig.agent_name) or audit_rates.get(sig.agent_name)
            if wr is not None:
                values.append(float(wr))
        if not values:
            return 0.5
        return sum(values) / len(values)

    def _signal_strength(
        self,
        signal: AgentSignal,
        boosts: dict[str, float],
        regime_key: str,
        backtest_rates: dict[str, float] | None = None,
        audit_rates: dict[str, float] | None = None,
        symbol_rates: dict[str, float] | None = None,
    ) -> float:
        boost = boosts.get(signal.agent_name, 1.0)
        regime_mult = self._regime_match_multiplier(signal.agent_name, regime_key)
        strength = signal.confidence * boost * regime_mult
        if symbol_rates and signal.agent_name in symbol_rates:
            win_rate = float(symbol_rates[signal.agent_name])
            if win_rate >= 0.65:
                strength *= 1.35
            elif win_rate >= 0.55:
                strength *= 1.15
            elif win_rate <= 0.34:
                strength *= 0.20
            elif win_rate < 0.45:
                strength *= 0.45
        elif audit_rates and signal.agent_name in audit_rates:
            win_rate = float(audit_rates[signal.agent_name])
            if win_rate < 0.35:
                strength *= 0.25
            elif win_rate < 0.45:
                strength *= 0.50
            elif win_rate < 0.50:
                strength *= 0.72
            elif win_rate >= 0.60:
                strength *= 1.12
        if backtest_rates and signal.agent_name in backtest_rates:
            win_rate = float(backtest_rates[signal.agent_name])
            if win_rate < 0.35:
                strength *= 0.30
            elif win_rate < 0.45:
                strength *= 0.50
            elif win_rate < 0.50:
                strength *= 0.72
        return strength

    def _apply_macro_alignment(
        self,
        symbol: str,
        direction: Direction,
        confidence: float,
        size_scale: float,
        context: dict[str, Any] | None,
        adx: float = 0.0,
    ) -> tuple[float, float, str]:
        if not context or not context.get("macro_regime"):
            return confidence, size_scale, ""
        macro = context["macro_regime"]
        bias = macro.get("bias", "neutral")
        usd = macro.get("usd_strength", "neutral")
        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        is_metal = symbol in {"XAU/USD", "XAG/USD"}
        note = ""

        if bias == "risk_off" and usd == "strong":
            is_fx = symbol in {
                "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD",
                "AUD/USD", "EUR/GBP", "EUR/CHF",
            }
            if is_crypto and direction == Direction.BUY:
                confidence *= 0.78
                size_scale *= 0.75
                note = "; macro risk-off reduces crypto long conviction"
            if is_crypto and direction == Direction.SELL:
                if adx >= 20:
                    confidence = min(confidence * 1.06, 1.0)
                    size_scale = min(size_scale * 1.08, 1.45)
                    note = "; macro risk-off + trend supports crypto shorts"
                else:
                    confidence *= 0.88
                    size_scale *= 0.85
                    note = "; macro risk-off but low ADX — reduced crypto short"
            elif is_metal and direction == Direction.BUY:
                confidence = min(confidence * 1.08, 1.0)
                size_scale = min(size_scale * 1.08, 1.5)
                note = "; risk-off safe-haven metals boost"
            elif (is_fx or is_metal) and direction == Direction.BUY:
                confidence *= 0.85
                size_scale *= 0.85
                note = "; macro risk-off + strong USD penalizes longs"
            elif is_metal and direction == Direction.SELL:
                confidence *= 0.72
                size_scale *= 0.70
                note = "; risk-off safe-haven — avoid metal shorts, prefer longs"
            elif is_fx and symbol in {"EUR/USD", "AUD/USD", "EUR/CHF", "GBP/USD"} and direction == Direction.SELL:
                confidence = min(confidence * 1.06, 1.0)
                size_scale = min(size_scale * 1.06, 1.45)
                note = "; risk-off USD strength supports FX shorts vs USD"
        elif bias == "risk_on" and usd == "weak":
            if is_crypto and direction == Direction.BUY:
                confidence = min(confidence * 1.08, 1.0)
                size_scale = min(size_scale * 1.10, 1.5)
                note = "; risk-on supports crypto longs"

        return confidence, size_scale, note

    def _build_ai_prompt(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> str:
        prompt_parts = [
            "You are the MetaOrchestrator for an AI trading competition ($1M account).",
            "Final Score = 70% Return Rank + 15% Drawdown Rank + 10% Sharpe Rank + 5% Discipline.",
            "Top competitors earn +$40k–$100k with 55–85% win rate — prioritize high-quality entries over churn.",
            "Take high-conviction trades on proven symbols (XAG, USD/CAD, AUD/USD). "
            "In risk-off: LONG metals (XAU/XAG), SHORT EUR/AUD/crypto — never short gold into safe-haven flows.",
            "Stay within rules: max ~15% drawdown, margin <88%, leverage <20x, no discipline violations.",
            f"Symbol: {features.symbol}, Regime: {features.regime.value}",
            f"ADX: {features.adx:.1f}, RSI: {features.rsi_14:.1f}, ATR: {features.atr_14:.4f}",
        ]
        for sig in signals:
            prompt_parts.append(
                f"Agent {sig.agent_name}: {sig.direction.value} conf={sig.confidence:.2f} — {sig.reasoning}"
            )
        if context:
            if context.get("semantic_best_agent"):
                prompt_parts.append(f"Semantic best agent: {context['semantic_best_agent']}")
            if context.get("working_memory"):
                prompt_parts.append(f"Recent trades: {len(context['working_memory'])}")
            if context.get("drawdown_pct"):
                prompt_parts.append(f"Drawdown: {context['drawdown_pct']:.1%}")
            if context.get("debate_synthesis"):
                prompt_parts.append(f"Bull/Bear debate: {context['debate_synthesis']}")
            if context.get("peer_sentiment"):
                prompt_parts.append(f"Peer crowd sentiment: {context['peer_sentiment']}")
            if context.get("sentiment_snapshot"):
                snap = context["sentiment_snapshot"]
                prompt_parts.append(
                    f"News sentiment: score={snap.get('score', 0):.2f} "
                    f"({snap.get('summary', '')})"
                )
                for headline in (snap.get("top_headlines") or [])[:3]:
                    prompt_parts.append(f"  Headline: {headline.get('title', '')} [{headline.get('source', '')}]")
            if context.get("macro_regime"):
                macro = context["macro_regime"]
                prompt_parts.append(
                    f"Macro regime: {macro.get('bias', 'neutral')}, USD {macro.get('usd_strength', 'neutral')}"
                )
            if context.get("upcoming_events"):
                for event in context["upcoming_events"][:3]:
                    prompt_parts.append(
                        f"Upcoming event: {event.get('name')} ({event.get('impact')}) at {event.get('scheduled_at')}"
                    )
            if context.get("event_gate") and not context["event_gate"].get("allowed", True):
                prompt_parts.append(f"Event gate: {context['event_gate'].get('reason', 'blocked')}")
            if context.get("ml_signal_confidence"):
                prompt_parts.append(
                    f"ML signal model: {context.get('ml_signal_direction', 'HOLD')} "
                    f"conf={context['ml_signal_confidence']:.2f}"
                )
            if context.get("backtest_agent_win_rates"):
                rates = context["backtest_agent_win_rates"]
                parts = [f"{k}={v:.0%}" for k, v in rates.items()]
                prompt_parts.append(f"Backtest agent win rates: {', '.join(parts)}")
        return "\n".join(prompt_parts)

    def _orchestrator_from_ai(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        ai: Any,
    ) -> OrchestratorDecision:
        direction_map = {
            "BUY": Direction.BUY,
            "SELL": Direction.SELL,
            "HOLD": Direction.HOLD,
        }
        direction = direction_map.get(str(ai.direction).upper(), Direction.HOLD)
        min_conf = self._min_confidence()
        if direction != Direction.HOLD and ai.confidence < min_conf:
            direction = Direction.HOLD
            ai_confidence = 0.0
            ai_reasoning = f"AI confidence {ai.confidence:.2f} below minimum {min_conf:.2f}"
        else:
            ai_confidence = ai.confidence
            ai_reasoning = ai.reasoning

        return OrchestratorDecision(
            symbol=features.symbol,
            direction=direction,
            confidence=ai_confidence,
            size_scale=ai.size_scale,
            reasoning=ai_reasoning,
            risk_assessment=ai.risk_assessment,
            agent_votes=signals,
            used_ai=True,
        )

    def _ai_decide(
        self,
        features: FeatureVector,
        signals: list[AgentSignal],
        context: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        from pydantic import BaseModel, Field, field_validator
        from pydantic_ai import Agent

        class AIDecision(BaseModel):
            direction: str = Field(description="BUY, SELL, or HOLD")
            confidence: float = Field(ge=0, le=1)
            size_scale: float = Field(ge=0.5, le=1.5, default=1.0)
            reasoning: str = ""
            risk_assessment: str = ""

            @field_validator("direction", mode="before")
            @classmethod
            def normalize_direction(cls, value: Any) -> str:
                if not isinstance(value, str):
                    return "HOLD"
                normalized = value.strip().upper()
                if normalized in {"BUY", "SELL", "HOLD"}:
                    return normalized
                return "HOLD"

            @field_validator("confidence", mode="before")
            @classmethod
            def clamp_confidence(cls, value: Any) -> float:
                try:
                    return max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    return 0.0

            @field_validator("size_scale", mode="before")
            @classmethod
            def clamp_size_scale(cls, value: Any) -> float:
                try:
                    return max(0.5, min(1.5, float(value)))
                except (TypeError, ValueError):
                    return 1.0

        from src.utils.llm_providers import (
            anthropic_llm_allowed,
            available_providers,
            openai_compat_env,
            orchestrator_use_complex_model,
            provider_order,
            resolve_model_for_provider,
        )

        anthropic_default = None
        if anthropic_llm_allowed():
            anthropic_default = self._anthropic_model_override or self._anthropic_config_model

        prompt = self._build_ai_prompt(features, signals, context)
        use_complex = orchestrator_use_complex_model()
        available = available_providers()
        failures: list[str] = []

        for provider_name in provider_order("orchestrator"):
            if not available.get(provider_name):
                continue

            model = "unknown"
            try:
                model, _ = resolve_model_for_provider(
                    provider_name,
                    role="orchestrator",
                    anthropic_default=anthropic_default,
                    complex=use_complex,
                )
                with openai_compat_env(provider_name):
                    agent = Agent(
                        model,
                        output_type=AIDecision,
                        system_prompt="Respond with structured trading decisions only.",
                    )
                    result = agent.run_sync(prompt)

                self._last_ai_call[features.symbol] = time.time()
                decision = self._orchestrator_from_ai(features, signals, result.output)
                macro_conf, macro_scale, macro_note = self._apply_macro_alignment(
                    features.symbol, decision.direction, decision.confidence,
                    decision.size_scale, context,
                )
                decision.confidence = macro_conf
                decision.size_scale = macro_scale
                if macro_note:
                    decision.reasoning += macro_note
                return decision
            except Exception as exc:
                failures.append(f"{provider_name}/{model}: {type(exc).__name__}: {exc}")
                logger.warning(
                    "AI decision failed for %s via %s model=%s: %s: %s",
                    features.symbol,
                    provider_name,
                    model,
                    type(exc).__name__,
                    exc,
                )

        raise RuntimeError(
            f"All LLM providers failed for {features.symbol}: {'; '.join(failures)}"
        )
