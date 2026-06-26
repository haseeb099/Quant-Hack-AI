"""Tests for MetaOrchestrator AI routing and structured output."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.agents.base_agent import AgentSignal, Direction, FeatureVector, Regime
from src.agents.meta_orchestrator import MetaOrchestrator, OrchestratorDecision


def _features(**overrides) -> FeatureVector:
    defaults = dict(
        symbol="EUR/USD",
        timeframe="M15",
        close=100.0,
        atr_14=1.0,
        atr_50=1.0,
        rsi_14=50.0,
        adx=20.0,
        ema_9=100.0,
        ema_21=99.0,
        ema_50=98.0,
        ema_200=95.0,
        bb_width=0.02,
        bb_width_percentile=50.0,
        donchian_high=101.0,
        donchian_low=99.0,
        volume_ratio=1.0,
        macd_histogram=0.0,
        regime=Regime.RANGING,
        extras={},
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


def _actionable_signals() -> list[AgentSignal]:
    return [
        AgentSignal("trend_surfer", "EUR/USD", Direction.BUY, 0.8, reasoning="up"),
        AgentSignal("mean_reversion", "EUR/USD", Direction.SELL, 0.78, reasoning="down"),
    ]


def test_use_ai_enabled_with_anthropic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.delenv("DOUBLEWORD_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    orch = MetaOrchestrator({"cooldown_minutes": 0}, {})

    assert orch._use_ai is True


@dataclass
class _FakeAIOutput:
    direction: str
    confidence: float
    size_scale: float
    reasoning: str
    risk_assessment: str = ""


def test_ai_decide_falls_back_to_second_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("QUANTAI_MIN_CONFIDENCE", "0.5")

    attempts: list[str] = []

    def fake_resolve(provider: str, **kwargs):
        attempts.append(provider)
        if provider == "anthropic":
            return "anthropic:claude-sonnet-4-6", provider
        return "openai-chat:openai/gpt-oss-20b", provider

    class FakeAgent:
        def __init__(self, model: str, **kwargs) -> None:
            self.model = model

        def run_sync(self, prompt: str):
            if self.model.startswith("anthropic:"):
                raise RuntimeError("anthropic unavailable")
            result = MagicMock()
            result.output = _FakeAIOutput(
                direction="BUY",
                confidence=0.82,
                size_scale=1.0,
                reasoning="doubleword fallback",
            )
            return result

    monkeypatch.setattr("src.utils.llm_providers.resolve_model_for_provider", fake_resolve)
    monkeypatch.setattr("pydantic_ai.Agent", FakeAgent)

    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.5}, {})
    decision = orch._ai_decide(_features(), _actionable_signals())

    assert attempts == ["anthropic", "doubleword"]
    assert decision.used_ai is True
    assert decision.direction == Direction.BUY
    assert decision.reasoning == "doubleword fallback"


def test_solo_ml_metal_sell_allowed_with_bear_debate() -> None:
    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.55}, {})
    features = _features(symbol="XAU/USD", regime=Regime.TRENDING, adx=42.0)
    signals = [
        AgentSignal("ml_signal", "XAU/USD", Direction.SELL, 0.71, reasoning="ml sell"),
    ]
    context = {
        "return_focus": True,
        "debate_winner": "bear",
        "debate_confidence": 0.80,
        "solo_ml_metal_sell_min_confidence": 0.68,
    }
    decision = orch._rule_based_decide(features, signals, context)
    decision = orch._finalize_decision(decision, signals, features, context)
    assert decision.direction == Direction.SELL
    assert decision.confidence >= 0.71
    assert "proven solo ml metal SELL" in decision.reasoning


def test_solo_audit_trend_surfer_allowed_in_trending() -> None:
    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.55}, {})
    features = _features(symbol="USD/CAD", regime=Regime.TRENDING, adx=28.0)
    signals = [
        AgentSignal("trend_surfer", "USD/CAD", Direction.SELL, 0.74, reasoning="down"),
    ]
    context = {
        "return_focus": True,
        "audit_winner_symbols": ["USD/CAD", "XAG/USD"],
        "audit_solo_trend_surfer_min_confidence": 0.72,
    }
    decision = orch._rule_based_decide(features, signals, context)
    decision = orch._finalize_decision(decision, signals, features, context)
    assert decision.direction == Direction.SELL
    assert decision.confidence >= 0.74
    assert "audit-winner solo trend_surfer" in decision.reasoning


def test_solo_trend_surfer_still_blocked_in_ranging() -> None:
    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.55}, {})
    features = _features(symbol="USD/CAD", regime=Regime.RANGING, adx=22.0)
    signals = [
        AgentSignal("trend_surfer", "USD/CAD", Direction.SELL, 0.74, reasoning="down"),
    ]
    context = {
        "return_focus": True,
        "audit_winner_symbols": ["USD/CAD", "XAG/USD"],
        "audit_solo_trend_surfer_min_confidence": 0.72,
    }
    decision = orch._rule_based_decide(features, signals, context)
    decision = orch._finalize_decision(decision, signals, features, context)
    assert decision.direction == Direction.HOLD


def test_ml_metal_sell_anchor_beats_ai_buy_flip() -> None:
    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.55}, {})
    features = _features(symbol="XAU/USD", regime=Regime.TRENDING, adx=42.0)
    signals = [
        AgentSignal("ml_signal", "XAU/USD", Direction.SELL, 0.81, reasoning="ml sell"),
    ]
    context = {
        "return_focus": True,
        "debate_winner": "bear",
        "debate_confidence": 0.86,
        "solo_ml_metal_sell_min_confidence": 0.68,
    }
    anchor = orch._ml_metal_sell_anchor_decision(features, signals, context)
    assert anchor is not None
    assert anchor.direction == Direction.SELL
    ai_buy = OrchestratorDecision(
        symbol="XAU/USD",
        direction=Direction.BUY,
        confidence=0.69,
        size_scale=1.0,
        reasoning="macro risk-off long",
        agent_votes=signals,
    )
    coerced = orch._prefer_winning_anchor(ai_buy, features, signals, context)
    assert coerced.direction == Direction.SELL


def test_audit_winner_dual_anchor_requires_both_agents() -> None:
    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.55}, {})
    features = _features(symbol="USD/CAD", regime=Regime.TRENDING, adx=28.0)
    signals = [
        AgentSignal("trend_surfer", "USD/CAD", Direction.SELL, 0.74, reasoning="down"),
        AgentSignal("ml_signal", "USD/CAD", Direction.SELL, 0.72, reasoning="ml"),
    ]
    context = {
        "return_focus": True,
        "audit_winner_symbols": ["USD/CAD", "XAG/USD"],
        "audit_winner_dual_min_adx": 26,
        "audit_winner_dual_min_confidence": 0.70,
        "block_direction_in_regimes": {"USD/CAD": {"SELL": ["ranging", "calm"]}},
    }
    dual = orch._audit_winner_dual_anchor_decision(features, signals, context)
    assert dual is not None
    assert dual.direction == Direction.SELL
    assert dual.confidence >= 0.70


def test_aidecision_validators_clamp_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("QUANTAI_MIN_CONFIDENCE", "0.5")

    class RecordingAgent:
        def __init__(self, model: str, output_type=None, **kwargs) -> None:
            self.output_type = output_type

        def run_sync(self, prompt: str):
            ai = self.output_type(
                direction="long",
                confidence=1.8,
                size_scale=9.9,
                reasoning="clamped",
            )
            result = MagicMock()
            result.output = ai
            return result

    monkeypatch.setattr("pydantic_ai.Agent", RecordingAgent)

    orch = MetaOrchestrator({"cooldown_minutes": 0, "min_agent_confidence": 0.5}, {})
    decision = orch._ai_decide(_features(), _actionable_signals())

    assert decision.direction == Direction.HOLD
    assert decision.confidence == 1.0
    assert decision.size_scale == 1.5
    assert decision.used_ai is True
