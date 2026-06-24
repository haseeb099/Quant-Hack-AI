"""LLM provider routing — Doubleword first, template fallback (no Anthropic for copilot)."""

from __future__ import annotations

import os
from typing import Any


def copilot_provider_name() -> str:
    if os.getenv("DOUBLEWORD_API_KEY", "").strip():
        return "doubleword"
    if os.getenv("PYDANTIC_AI_GATEWAY_API_KEY", "").strip():
        return "logfire_gateway"
    if os.getenv("GROQ_API_KEY", "").strip() or os.getenv("Groq_API_KEY", "").strip():
        return "groq"
    return "template"


def _copilot_model() -> str:
    if os.getenv("PYDANTIC_AI_GATEWAY_API_KEY", "").strip() and not os.getenv("DOUBLEWORD_API_KEY", "").strip():
        return os.getenv("COPILOT_GATEWAY_MODEL", "gateway/openai:gpt-4o-mini")
    from src.utils.llm_providers import copilot_llm_enabled, resolve_llm_model

    model, _provider = resolve_llm_model(role="copilot")
    return model


def enhance_summary_with_llm(context: dict[str, Any], template_summary: str) -> tuple[str, str]:
    """Optional narrative enhancement. Returns (summary, provider). Never invents prices."""
    provider = copilot_provider_name()
    if provider == "template":
        return template_summary, provider

    try:
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent

        class Narrative(BaseModel):
            summary: str = Field(description="2-4 sentences grounded in provided facts only")
            risks: list[str] = Field(default_factory=list, max_length=5)

        model = _copilot_model()

        market = context.get("market", {})
        facts = {
            "symbol": context.get("symbol"),
            "mid": market.get("mid"),
            "regime": market.get("regime"),
            "session": context.get("session"),
            "dd_tier": context.get("risk", {}).get("dd_tier"),
            "agent_votes": [
                {"agent": s.agent_name, "direction": s.direction.value, "confidence": s.confidence}
                for s in context.get("agent_signals", [])
            ],
            "template_summary": template_summary,
        }

        agent = Agent(
            model,
            output_type=Narrative,
            system_prompt=(
                "You are a trading copilot. Use ONLY the facts JSON provided. "
                "Never invent prices, positions, or P&L. If data is missing, say so."
            ),
        )
        result = agent.run_sync(
            f"Summarize this setup for the trader:\n{facts}",
        )
        out = result.output
        return out.summary, provider
    except Exception:
        return template_summary, "template"
