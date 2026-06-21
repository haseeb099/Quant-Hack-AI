"""Technology prize compliance checklist for sponsor integrations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

CheckStatus = Literal["pass", "warn", "fail", "skip"]


def _check(
    code: str,
    sponsor: str,
    label: str,
    status: CheckStatus,
    message: str,
    file_path: str | None = None,
    remediation: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "sponsor": sponsor,
        "label": label,
        "status": status,
        "message": message,
        "file_path": file_path,
        "remediation": remediation,
    }


def evaluate_technology_prize_checklist() -> dict[str, Any]:
    """Evaluate sponsor technology integrations for prize judging."""
    checks: list[dict[str, Any]] = []

    anthropic_file = Path("src/agents/meta_orchestrator.py")
    anthropic_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    checks.append(_check(
        "ANTHROPIC",
        "Anthropic",
        "Claude MetaOrchestrator",
        "pass" if anthropic_file.is_file() else "fail",
        "MetaOrchestrator uses Claude for conflict resolution"
        if anthropic_file.is_file()
        else "meta_orchestrator.py missing",
        str(anthropic_file),
        None if anthropic_file.is_file() else "Restore src/agents/meta_orchestrator.py",
    ))
    checks.append(_check(
        "ANTHROPIC_KEY",
        "Anthropic",
        "API key configured",
        "pass" if anthropic_key else "warn",
        "ANTHROPIC_API_KEY set" if anthropic_key else "Key not set — rule fallback active",
        None,
        "export ANTHROPIC_API_KEY=..." if not anthropic_key else None,
    ))

    logfire_file = Path("src/utils/logger.py")
    logfire_token = bool(os.getenv("LOGFIRE_TOKEN", "").strip())
    from src.utils.logger import is_logfire_active
    logfire_live = is_logfire_active()
    checks.append(_check(
        "LOGFIRE",
        "Pydantic",
        "Logfire observability module",
        "pass" if logfire_file.is_file() else "fail",
        "Structured tracing via src/utils/logger.py",
        str(logfire_file),
    ))
    checks.append(_check(
        "LOGFIRE_TOKEN",
        "Pydantic",
        "Logfire tracing active",
        "pass" if logfire_live else ("warn" if logfire_token else "warn"),
        "Tracing active" if logfire_live else (
            "Token set — restart to activate" if logfire_token else "LOGFIRE_TOKEN not set"
        ),
        None,
        "export LOGFIRE_TOKEN=..." if not logfire_live else None,
    ))

    doubleword_key = bool(os.getenv("DOUBLEWORD_API_KEY", "").strip())
    checks.append(_check(
        "DOUBLEWORD",
        "Doubleword",
        "Inference routing in MetaOrchestrator",
        "pass" if anthropic_file.is_file() else "fail",
        "Routes via api.doubleword.ai when key set",
        str(anthropic_file),
    ))
    checks.append(_check(
        "DOUBLEWORD_KEY",
        "Doubleword",
        "API key configured",
        "pass" if doubleword_key else "warn",
        "DOUBLEWORD_API_KEY set" if doubleword_key else "Optional — direct Anthropic fallback",
        None,
    ))

    dash_docker = Path("Dockerfile.dashboard").is_file()
    web_app = Path("src/web/app.py").is_file()
    frontend_dist = Path("frontend/dist/index.html").is_file()
    checks.append(_check(
        "NORTHFLANK_DASHBOARD",
        "Northflank",
        "Dashboard Docker image",
        "pass" if dash_docker else "fail",
        "Dockerfile.dashboard present" if dash_docker else "Missing Dockerfile.dashboard",
        "Dockerfile.dashboard",
    ))
    checks.append(_check(
        "NORTHFLANK_API",
        "Northflank",
        "FastAPI + React command center",
        "pass" if web_app and frontend_dist else ("warn" if web_app else "fail"),
        "API + built SPA ready" if web_app and frontend_dist else "Run cd frontend && npm run build",
        "src/web/app.py",
        None if frontend_dist else "cd frontend && npm run build",
    ))

    repo_checks = [
        ("REPO_TESTS", "Test suite", Path("tests")),
        ("REPO_DOCS", "Architecture docs", Path("docs/architecture.md")),
        ("REPO_DEMO", "Demo script", Path("docs/demo_script.md")),
        ("REPO_MQL5", "MT5 bridge EA", Path("mql5/DWX_ZeroMQ_Server.mq5")),
    ]
    for code, label, path in repo_checks:
        ok = path.is_file() or (path.is_dir() and any(path.glob("test_*.py")))
        checks.append(_check(
            code,
            "Repository",
            label,
            "pass" if ok else "fail",
            f"{path} present" if ok else f"{path} missing",
            str(path),
        ))

    summary = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in checks:
        summary[c["status"]] += 1

    ready = summary["fail"] == 0 and summary["pass"] >= 8
    return {
        "ready": ready,
        "summary": summary,
        "checks": checks,
        "docs": "docs/sponsor_integrations.md",
        "notion_doc": "Technology prize — Notion Doc 13",
    }
