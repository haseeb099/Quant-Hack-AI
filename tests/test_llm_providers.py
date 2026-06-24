"""Tests for shared LLM provider routing."""

from __future__ import annotations

import os

import pytest

from src.agents.base_agent import AgentSignal, Direction
from src.agents.meta_orchestrator import MetaOrchestrator
from src.utils.llm_providers import (
    copilot_llm_enabled,
    has_llm_providers,
    openai_compat_env,
    orchestrator_ai_on_conflict_only,
    provider_order,
    resolve_llm_model,
    resolve_model_for_provider,
    routing_summary,
)


def test_resolve_doubleword_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "auto")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("DOUBLEWORD_MODEL", "openai/gpt-oss-20b")

    model, provider = resolve_llm_model(role="orchestrator")

    assert provider == "doubleword"
    assert model == "openai-chat:openai/gpt-oss-20b"


def test_resolve_complex_orchestrator_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "doubleword")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("DOUBLEWORD_MODEL_COMPLEX", "openai/gpt-oss-120b")

    model, provider = resolve_llm_model(role="orchestrator", complex=True)

    assert provider == "doubleword"
    assert model == "openai-chat:openai/gpt-oss-120b"


def test_resolve_anthropic_when_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("META_ORCHESTRATOR_MODEL", "claude-sonnet-4-6")

    model, provider = resolve_llm_model(role="orchestrator")

    assert provider == "anthropic"
    assert model == "anthropic:claude-sonnet-4-6"


def test_resolve_anthropic_for_sentiment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("SENTIMENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("SENTIMENT_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

    model, provider = resolve_llm_model(role="sentiment")

    assert provider == "anthropic"
    assert model == "anthropic:claude-3-5-haiku-20241022"


def test_sentiment_lexicon_first_false_when_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.delenv("SENTIMENT_LEXICON_FIRST", raising=False)

    from src.utils.llm_providers import sentiment_lexicon_first

    assert sentiment_lexicon_first() is False


def test_groq_before_anthropic_in_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "auto")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")

    model, provider = resolve_llm_model(role="sentiment")

    assert provider == "groq"
    assert model == "openai-chat:llama-3.3-70b-versatile"


def test_role_specific_doubleword_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "doubleword")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("COPILOT_DOUBLEWORD_MODEL", "openai/gpt-oss-20b")

    model, provider = resolve_llm_model(role="copilot")

    assert provider == "doubleword"
    assert model == "openai-chat:openai/gpt-oss-20b"


def test_cost_flags_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COPILOT_USE_LLM", raising=False)
    monkeypatch.delenv("META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY", raising=False)
    monkeypatch.delenv("QUANTAI_LLM_PROVIDER", raising=False)

    assert copilot_llm_enabled() is False
    assert orchestrator_ai_on_conflict_only() is True


def test_anthropic_disabled_by_default_even_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")

    model, provider = resolve_llm_model(role="orchestrator")

    assert provider == "doubleword"


def test_orchestrator_ai_always_when_claude_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY", raising=False)

    assert orchestrator_ai_on_conflict_only() is False


def test_routing_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("QUANTAI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("COPILOT_USE_LLM", "false")

    info = routing_summary()

    assert info["orchestrator_mode"] == "always"
    assert info["sentiment_mode"] == "claude-first"
    assert info["copilot_mode"] == "template-only"
    assert "claude" in info["sentiment"]


def test_orchestrator_skips_ai_on_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY", "true")
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")
    monkeypatch.setenv("QUANTAI_MIN_CONFIDENCE", "0.5")

    orch = MetaOrchestrator({"min_agent_confidence": 0.5, "cooldown_minutes": 0}, {})
    signals = [
        AgentSignal("trend_surfer", "EUR/USD", Direction.BUY, 0.8, reasoning="up"),
        AgentSignal("breakout_hunter", "EUR/USD", Direction.BUY, 0.78, reasoning="up"),
        AgentSignal("mean_reversion", "EUR/USD", Direction.BUY, 0.76, reasoning="up"),
    ]

    assert orch._signals_need_ai(signals) is False

    conflict = [
        AgentSignal("trend_surfer", "EUR/USD", Direction.BUY, 0.8, reasoning="up"),
        AgentSignal("mean_reversion", "EUR/USD", Direction.SELL, 0.78, reasoning="down"),
    ]
    assert orch._signals_need_ai(conflict) is True


def test_has_llm_providers_with_anthropic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.delenv("DOUBLEWORD_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert has_llm_providers("orchestrator") is True


def test_resolve_model_for_provider_splits_anthropic_and_doubleword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_ORCHESTRATOR_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("DOUBLEWORD_MODEL", "openai/gpt-oss-20b")

    anthropic_model, provider = resolve_model_for_provider("anthropic", role="orchestrator")
    doubleword_model, provider = resolve_model_for_provider("doubleword", role="orchestrator")

    assert provider == "doubleword"
    assert anthropic_model == "anthropic:claude-sonnet-4-6"
    assert doubleword_model == "openai-chat:openai/gpt-oss-20b"


def test_openai_compat_env_does_not_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "dw-test")

    with openai_compat_env("doubleword"):
        assert os.environ["OPENAI_API_KEY"] == "dw-test"

    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_provider_order_respects_role_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "true")
    monkeypatch.setenv("ORCHESTRATOR_LLM_PROVIDER", "anthropic")

    assert provider_order("orchestrator") == ["anthropic", "doubleword", "groq"]
