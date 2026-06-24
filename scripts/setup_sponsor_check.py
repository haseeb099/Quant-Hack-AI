#!/usr/bin/env python3
"""Validate competition sponsor perk configuration (Anthropic, Logfire, Doubleword, Northflank)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

SPONSOR_LINKS = {
    "anthropic": "https://platform.claude.com",
    "pydantic_hackathon": "https://pydantic.dev/hackathon",
    "logfire": "https://logfire.pydantic.dev",
    "northflank": "https://app.northflank.com/i/AIENGINE",
    "northflank_gpu": "https://northflank.com",  # use competition GPU registration form URL from portal
}


def _masked(value: str) -> str:
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return f"{v[:4]}…{v[-4:]}"


def _check(
    code: str,
    label: str,
    ok: bool,
    detail: str,
    fix: str | None = None,
    warn: bool = False,
) -> dict[str, Any]:
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    return {"code": code, "label": label, "status": status, "detail": detail, "fix": fix}


def check_anthropic() -> dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    allow_anthropic = os.getenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    groq = os.getenv("GROQ_API_KEY", "").strip() or os.getenv("Groq_API_KEY", "").strip()
    doubleword = os.getenv("DOUBLEWORD_API_KEY", "").strip()
    provider = os.getenv("QUANTAI_LLM_PROVIDER", "auto").strip().lower() or "auto"

    if not key:
        return _check(
            "ANTHROPIC",
            "Anthropic (MetaOrchestrator)",
            False,
            "ANTHROPIC_API_KEY not set",
            f"Redeem $50 credits at {SPONSOR_LINKS['anthropic']} -> API Keys -> paste into .env",
        )

    detail = f"key configured ({_masked(key)})"
    if not allow_anthropic:
        if doubleword or groq:
            return _check(
                "ANTHROPIC",
                "Anthropic (MetaOrchestrator fallback)",
                True,
                detail + " — reserved; set QUANTAI_LLM_ALLOW_ANTHROPIC=true to enable Claude",
            )
        return _check(
            "ANTHROPIC",
            "Anthropic (MetaOrchestrator)",
            False,
            detail + " — key set but QUANTAI_LLM_ALLOW_ANTHROPIC is false and no Doubleword/Groq key",
            "Set QUANTAI_LLM_ALLOW_ANTHROPIC=true (and optionally QUANTAI_LLM_PROVIDER=anthropic) "
            "or add DOUBLEWORD_API_KEY / GROQ_API_KEY for live orchestrator AI",
        )

    if provider == "anthropic":
        return _check("ANTHROPIC", "Anthropic (MetaOrchestrator)", True, detail)
    if doubleword or provider in ("doubleword", "auto"):
        return _check(
            "ANTHROPIC",
            "Anthropic (MetaOrchestrator fallback)",
            True,
            detail + " — available in provider chain after Doubleword/Groq",
        )
    if groq and provider == "groq":
        return _check(
            "ANTHROPIC",
            "Anthropic (MetaOrchestrator fallback)",
            True,
            detail + " — available in provider chain after Groq",
        )
    return _check("ANTHROPIC", "Anthropic (MetaOrchestrator fallback)", True, detail)


def check_orchestrator_ai() -> dict[str, Any]:
    from src.utils.llm_providers import (
        has_llm_providers,
        orchestrator_use_complex_model,
        provider_order,
        resolve_llm_model,
    )

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    allow_anthropic = os.getenv("QUANTAI_LLM_ALLOW_ANTHROPIC", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if anthropic_key and allow_anthropic and not has_llm_providers("orchestrator"):
        return _check(
            "ORCHESTRATOR_AI",
            "MetaOrchestrator AI enablement",
            False,
            "ANTHROPIC_API_KEY is set and allowed, but no orchestrator provider is available",
            "Verify QUANTAI_LLM_PROVIDER / ORCHESTRATOR_LLM_PROVIDER and API keys",
        )

    if anthropic_key and not allow_anthropic and not has_llm_providers("orchestrator"):
        return _check(
            "ORCHESTRATOR_AI",
            "MetaOrchestrator AI enablement",
            False,
            "Anthropic key present but orchestrator AI is disabled",
            "Set QUANTAI_LLM_ALLOW_ANTHROPIC=true or add DOUBLEWORD_API_KEY / GROQ_API_KEY",
        )

    if not has_llm_providers("orchestrator"):
        return _check(
            "ORCHESTRATOR_AI",
            "MetaOrchestrator AI enablement",
            True,
            "No LLM keys — orchestrator will use rule-based fallback",
            warn=True,
        )

    try:
        model, provider = resolve_llm_model(
            role="orchestrator",
            complex=orchestrator_use_complex_model(),
        )
        chain = " -> ".join(provider_order("orchestrator"))
        return _check(
            "ORCHESTRATOR_AI",
            "MetaOrchestrator AI enablement",
            True,
            f"primary={provider} ({model.split(':', 1)[-1]}); chain={chain}",
        )
    except RuntimeError as exc:
        return _check(
            "ORCHESTRATOR_AI",
            "MetaOrchestrator AI enablement",
            False,
            str(exc),
            "Fix provider keys and QUANTAI_LLM_ALLOW_ANTHROPIC before live trading",
        )


def check_logfire() -> dict[str, Any]:
    token = os.getenv("LOGFIRE_TOKEN", "").strip()
    if not token:
        return _check(
            "LOGFIRE",
            "Pydantic Logfire (observability)",
            False,
            "LOGFIRE_TOKEN not set",
            f"Redeem hackathon credits at {SPONSOR_LINKS['pydantic_hackathon']} -> "
            f"create project at {SPONSOR_LINKS['logfire']} -> Settings -> Write tokens",
        )

    active = False
    try:
        from src.utils.logger import is_logfire_active, setup_logging

        setup_logging(enable_logfire=True)
        active = is_logfire_active()
    except Exception as exc:
        return _check(
            "LOGFIRE",
            "Pydantic Logfire (observability)",
            False,
            f"token set ({_masked(token)}) but init failed: {exc}",
            "pip install logfire && restart engine/dashboard",
        )

    if not active:
        return _check(
            "LOGFIRE",
            "Pydantic Logfire (observability)",
            False,
            f"token set ({_masked(token)}) but tracing not active in this process",
            "Restart with LOGFIRE_TOKEN exported; avoid --no-logfire",
            warn=True,
        )
    return _check("LOGFIRE", "Pydantic Logfire (observability)", True, f"tracing active ({_masked(token)})")


def check_doubleword() -> dict[str, Any]:
    direct = os.getenv("DOUBLEWORD_API_KEY", "").strip()
    gateway = os.getenv("PYDANTIC_AI_GATEWAY_API_KEY", "").strip()
    model = os.getenv("COPILOT_GATEWAY_MODEL", "gateway/openai:gpt-4o-mini").strip()

    if direct:
        model = os.getenv("DOUBLEWORD_MODEL", "openai/gpt-oss-20b").strip()
        return _check(
            "DOUBLEWORD",
            "Doubleword (orchestrator + copilot)",
            True,
            f"DOUBLEWORD_API_KEY set ({_masked(direct)}) -> {model} via api.doubleword.ai",
        )
    if gateway:
        return _check(
            "DOUBLEWORD",
            "Doubleword (Copilot inference)",
            True,
            f"Logfire Gateway key set ({_masked(gateway)}), model={model}",
        )
    return _check(
        "DOUBLEWORD",
        "Doubleword (Copilot inference)",
        False,
        "No Doubleword or Logfire Gateway key",
        f"Perk is via Logfire Gateway: redeem at {SPONSOR_LINKS['pydantic_hackathon']} -> "
        "Logfire -> Gateway -> create API key -> set PYDANTIC_AI_GATEWAY_API_KEY in .env "
        "(or set DOUBLEWORD_API_KEY if you received a direct key)",
        warn=True,
    )


def check_northflank() -> dict[str, Any]:
    dash_auth = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    docker_dash = (ROOT / "Dockerfile.dashboard").is_file()
    docker_eng = (ROOT / "Dockerfile.engine").is_file()
    dist = (ROOT / "frontend" / "dist" / "index.html").is_file()

    issues: list[str] = []
    if not docker_dash or not docker_eng:
        issues.append("Dockerfiles missing")
    if not dist:
        issues.append("frontend/dist not built")
    if not dash_auth:
        issues.append("DASHBOARD_AUTH_TOKEN not set (required for public ingress)")

    if not issues:
        return _check(
            "NORTHFLANK",
            "Northflank deploy readiness",
            True,
            "Dockerfiles, SPA build, and dashboard auth token present",
        )

    return _check(
        "NORTHFLANK",
        "Northflank deploy readiness",
        len(issues) == 1 and "DASHBOARD_AUTH_TOKEN" in issues[0],
        "; ".join(issues),
        f"Sign up: {SPONSOR_LINKS['northflank']} ($100 credit). "
        "Build: cd frontend && npm run build. "
        "Set DASHBOARD_AUTH_TOKEN. See docs/northflank_deploy.md",
        warn=len(issues) <= 2,
    )


def routing_summary() -> str:
    from src.utils.llm_providers import routing_summary as llm_routing

    info = llm_routing()
    return (
        f"MetaOrchestrator -> {info['orchestrator']} ({info['orchestrator_mode']}) | "
        f"Copilot -> {info['copilot']} ({info['copilot_mode']}) | "
        f"Sentiment -> {info['sentiment_mode']}"
    )


def main() -> int:
    print("QuantAI sponsor perk setup check\n")
    checks = [
        check_anthropic(),
        check_orchestrator_ai(),
        check_logfire(),
        check_doubleword(),
        check_northflank(),
    ]

    fails = 0
    warns = 0
    for c in checks:
        print(f"[{c['status']}] {c['label']}: {c['detail']}")
        if c.get("fix"):
            print(f"       -> {c['fix']}")
        if c["status"] == "FAIL":
            fails += 1
        elif c["status"] == "WARN":
            warns += 1

    print(f"\nRouting: {routing_summary()}")
    print("\nRecommended cost-aware routing:")
    print("  - Engine: ANTHROPIC_API_KEY + QUANTAI_LLM_ALLOW_ANTHROPIC=true + QUANTAI_LLM_PROVIDER=anthropic")
    print("  - Or: DOUBLEWORD_API_KEY + QUANTAI_LLM_PROVIDER=doubleword (Groq fallback)")
    print("  - Copilot: PYDANTIC_AI_GATEWAY_API_KEY (Doubleword via Logfire Gateway)")
    print("  - LOGFIRE_TOKEN on engine + dashboard")
    print(f"  - Northflank: {SPONSOR_LINKS['northflank']}")

    if fails:
        print(f"\n{fails} required perk(s) need configuration.")
        return 1
    if warns:
        print(f"\n{warns} warning(s) — review routing before Round 1.")
    else:
        print("\nAll sponsor perks configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
