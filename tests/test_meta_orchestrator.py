"""Tests for MetaOrchestrator AI routing and structured output."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.agents.base_agent import AgentSignal, Direction, FeatureVector, Regime
from src.agents.meta_orchestrator import MetaOrchestrator


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
