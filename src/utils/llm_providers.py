"""Shared LLM provider routing — Claude for sentiment/orchestrator when configured."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

DOUBLEWORD_BASE_URL = "https://api.doubleword.ai/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_ROLE_DEFAULT_DOUBLEWORD_MODEL = {
    "orchestrator": "openai/gpt-oss-20b",
    "copilot": "openai/gpt-oss-20b",
    "sentiment": "google/gemma-4-31B-it",
}

_ROLE_DEFAULT_ANTHROPIC_MODEL = {
    "orchestrator": "claude-sonnet-4-6",
    "sentiment": "claude-3-5-haiku-20241022",
    "copilot": "claude-sonnet-4-6",
}

_ROLE_ENV_KEYS = {
    "orchestrator": ("DOUBLEWORD_MODEL", "META_ORCHESTRATOR_DOUBLEWORD_MODEL"),
    "copilot": ("COPILOT_DOUBLEWORD_MODEL",),
    "sentiment": ("SENTIMENT_DOUBLEWORD_MODEL",),
}

_ROLE_ANTHROPIC_ENV_KEYS = {
    "orchestrator": ("META_ORCHESTRATOR_MODEL",),
    "sentiment": ("SENTIMENT_ANTHROPIC_MODEL",),
    "copilot": ("COPILOT_ANTHROPIC_MODEL",),
}

_ROLE_PROVIDER_ENV = {
    "orchestrator": "ORCHESTRATOR_LLM_PROVIDER",
    "sentiment": "SENTIMENT_LLM_PROVIDER",
    "copilot": "COPILOT_LLM_PROVIDER",
}


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def anthropic_llm_allowed() -> bool:
    """Anthropic is opt-in only; default off (use Doubleword/Groq)."""
    return env_bool("QUANTAI_LLM_ALLOW_ANTHROPIC", False)


def llm_provider_preference() -> str:
    return os.getenv("QUANTAI_LLM_PROVIDER", "auto").strip().lower() or "auto"


def role_llm_provider(role: str) -> str | None:
    """Per-role provider override, e.g. SENTIMENT_LLM_PROVIDER=anthropic."""
    env_key = _ROLE_PROVIDER_ENV.get(role)
    if not env_key:
        return None
    value = os.getenv(env_key, "").strip().lower()
    return value or None


def copilot_llm_enabled() -> bool:
    return env_bool("COPILOT_USE_LLM", False)


def sentiment_llm_enabled(default: bool = True) -> bool:
    return env_bool("SENTIMENT_LLM_ENABLED", default)


def sentiment_lexicon_first() -> bool:
    """When false and an LLM is configured, Claude/other LLM scores headlines first."""
    if role_llm_provider("sentiment") == "anthropic" or llm_provider_preference() == "anthropic":
        return env_bool("SENTIMENT_LEXICON_FIRST", False)
    return env_bool("SENTIMENT_LEXICON_FIRST", True)


def sentiment_claude_preferred() -> bool:
    available = _available_providers()
    if not available.get("anthropic"):
        return False
    if role_llm_provider("sentiment") == "anthropic":
        return True
    return llm_provider_preference() == "anthropic"


def orchestrator_ai_on_conflict_only() -> bool:
    if llm_provider_preference() == "anthropic" and role_llm_provider("orchestrator") != "doubleword":
        return env_bool("META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY", False)
    return env_bool("META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY", True)


def orchestrator_use_complex_model() -> bool:
    return env_bool("META_ORCHESTRATOR_COMPLEX_MODEL", False)


def _provider_chain(preference: str) -> list[str]:
    if preference == "anthropic":
        if anthropic_llm_allowed():
            return ["anthropic", "doubleword", "groq"]
        return ["doubleword", "groq"]

    if preference == "doubleword":
        chain = ["doubleword", "groq"]
        if anthropic_llm_allowed():
            chain.append("anthropic")
        return chain

    if preference == "groq":
        chain = ["groq", "doubleword"]
        if anthropic_llm_allowed():
            chain.append("anthropic")
        return chain

    chain = ["doubleword", "groq"]
    if anthropic_llm_allowed():
        chain.append("anthropic")
    return chain


def provider_order(role: str = "orchestrator") -> list[str]:
    """Ordered provider names for a role (respects per-role and global preference)."""
    return _provider_order(role)


def _provider_order(role: str = "orchestrator") -> list[str]:
    role_pref = role_llm_provider(role)
    if role_pref:
        return _provider_chain(role_pref)
    return _provider_chain(llm_provider_preference())


def _available_providers() -> dict[str, bool]:
    return {
        "anthropic": anthropic_llm_allowed()
        and bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "doubleword": bool(os.getenv("DOUBLEWORD_API_KEY", "").strip()),
        "groq": bool((os.getenv("GROQ_API_KEY") or os.getenv("Groq_API_KEY") or "").strip()),
    }


def available_providers() -> dict[str, bool]:
    """Return which LLM providers are configured and allowed."""
    return _available_providers()


def has_llm_providers(role: str = "orchestrator") -> bool:
    """True when at least one provider in the role chain has credentials."""
    available = _available_providers()
    return any(available.get(provider) for provider in provider_order(role))


def _doubleword_model(role: str, *, complex: bool = False) -> str:
    if complex and role == "orchestrator":
        complex_model = os.getenv("DOUBLEWORD_MODEL_COMPLEX", "").strip()
        if complex_model:
            return complex_model
        return "openai/gpt-oss-120b"

    for key in _ROLE_ENV_KEYS.get(role, ("DOUBLEWORD_MODEL",)):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return _ROLE_DEFAULT_DOUBLEWORD_MODEL.get(role, "openai/gpt-oss-20b")


def _groq_model(role: str) -> str:
    role_key = {
        "orchestrator": "GROQ_ORCHESTRATOR_MODEL",
        "copilot": "GROQ_COPILOT_MODEL",
        "sentiment": "GROQ_SENTIMENT_MODEL",
    }.get(role, "")
    if role_key:
        value = os.getenv(role_key, "").strip()
        if value:
            return value
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"


def _anthropic_model(role: str, anthropic_default: str | None = None) -> str:
    for key in _ROLE_ANTHROPIC_ENV_KEYS.get(role, ()):
        value = os.getenv(key, "").strip()
        if value:
            return value

    if anthropic_default:
        return anthropic_default

    return _ROLE_DEFAULT_ANTHROPIC_MODEL.get(role, "claude-sonnet-4-6")


def resolve_model_for_provider(
    provider: str,
    *,
    role: str = "orchestrator",
    anthropic_default: str | None = None,
    complex: bool = False,
) -> tuple[str, str]:
    """Return (pydantic_ai model string, provider name) for a specific provider."""
    if provider == "doubleword":
        return f"openai-chat:{_doubleword_model(role, complex=complex)}", "doubleword"
    if provider == "groq":
        return f"openai-chat:{_groq_model(role)}", "groq"
    if provider == "anthropic":
        model = _anthropic_model(role, anthropic_default)
        return f"anthropic:{model}", "anthropic"
    raise ValueError(f"Unknown LLM provider: {provider}")


@contextmanager
def openai_compat_env(provider: str) -> Iterator[None]:
    """Temporarily set OPENAI_* for pydantic-ai openai-chat providers."""
    if provider not in ("doubleword", "groq"):
        yield
        return

    if provider == "doubleword":
        api_key = os.getenv("DOUBLEWORD_API_KEY", "")
        base_url = DOUBLEWORD_BASE_URL
    else:
        api_key = os.getenv("GROQ_API_KEY") or os.getenv("Groq_API_KEY", "")
        base_url = GROQ_BASE_URL

    saved = {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
    }
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve_llm_model(
    *,
    role: str = "orchestrator",
    anthropic_default: str | None = None,
    complex: bool = False,
) -> tuple[str, str]:
    """Return (pydantic_ai model string, provider name) for the first available provider."""
    available = _available_providers()
    for provider in _provider_order(role):
        if not available.get(provider):
            continue
        return resolve_model_for_provider(
            provider,
            role=role,
            anthropic_default=anthropic_default,
            complex=complex,
        )

    raise RuntimeError(
        "No LLM provider configured — set DOUBLEWORD_API_KEY, GROQ_API_KEY, "
        "or ANTHROPIC_API_KEY with QUANTAI_LLM_ALLOW_ANTHROPIC=true"
    )


def routing_summary() -> dict[str, str]:
    """Human-readable routing snapshot for dashboards and setup scripts."""
    lines: dict[str, str] = {}

    try:
        model, provider = resolve_llm_model(role="orchestrator", complex=orchestrator_use_complex_model())
        lines["orchestrator"] = f"{provider} ({model.split(':', 1)[-1]})"
    except RuntimeError:
        lines["orchestrator"] = "rule-based fallback"

    try:
        model, provider = resolve_llm_model(role="sentiment")
        lines["sentiment"] = f"{provider} ({model.split(':', 1)[-1]})"
    except RuntimeError:
        lines["sentiment"] = "lexicon-only"

    try:
        model, provider = resolve_llm_model(role="copilot")
        lines["copilot"] = f"{provider} ({model.split(':', 1)[-1]})"
    except RuntimeError:
        lines["copilot"] = "template"

    lines["copilot_mode"] = "llm" if copilot_llm_enabled() else "template-only"
    lines["orchestrator_mode"] = "conflict-only" if orchestrator_ai_on_conflict_only() else "always"
    if not sentiment_llm_enabled():
        lines["sentiment_mode"] = "lexicon-only"
    elif sentiment_lexicon_first():
        lines["sentiment_mode"] = "lexicon-first"
    elif sentiment_claude_preferred():
        lines["sentiment_mode"] = "claude-first"
    else:
        lines["sentiment_mode"] = "llm-first"

    return lines
