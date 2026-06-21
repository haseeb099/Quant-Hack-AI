"""Competition launch preflight — go/no-go checklist for live deployment."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.engine.config import load_yaml
from src.integrations.notion_sync import notion_sync_enabled
from src.utils.logger import is_logfire_active
from src.web.routes._helpers import is_state_stale, resolve_data_source, state_age_seconds
from src.web.runtime_state import read_state

CheckStatus = Literal["pass", "warn", "fail", "skip"]

# Competition launch — Round 1 (BST). Stored as UTC ISO for API consumers.
COMPETITION_LAUNCH_UTC = datetime(2026, 6, 21, 21, 0, tzinfo=timezone.utc)


def _check(
    code: str,
    label: str,
    status: CheckStatus,
    message: str,
    remediation: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "remediation": remediation,
    }


def evaluate_launch_readiness(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return structured go/no-go checklist grounded in runtime state and env."""
    state = state or read_state()
    mode = str(state.get("mode", "simulate"))
    is_live = mode == "live"
    checks: list[dict[str, Any]] = []

    engine_running = bool(state.get("engine_running"))
    checks.append(_check(
        "ENGINE_RUNNING",
        "Trading engine",
        "pass" if engine_running else "fail",
        "Engine running" if engine_running else "Engine not running",
        None if engine_running else "Start engine: python main.py --mode live --phase round1 --with-dashboard",
    ))

    if state.get("engine_paused"):
        checks.append(_check(
            "ENGINE_PAUSED",
            "Engine pause state",
            "warn",
            "Engine is paused — no cycles will execute",
            "Resume from dashboard control bar or POST /api/engine/resume",
        ))

    stale = is_state_stale(state)
    checks.append(_check(
        "STATE_FRESH",
        "Dashboard state",
        "pass" if not stale else "fail",
        "State fresh" if not stale else f"State stale ({state_age_seconds(state):.0f}s old)",
        None if not stale else "Restart engine or check data/runtime_state.json publisher",
    ))

    mt5 = bool(state.get("mt5_connected"))
    if is_live:
        checks.append(_check(
            "MT5_BRIDGE",
            "MT5 / ZeroMQ bridge",
            "pass" if mt5 else "fail",
            "Bridge connected" if mt5 else "Bridge offline",
            None if mt5 else "Enable DWX_ZeroMQ_Server in MT5; run scripts/zmq_diagnose.py",
        ))
        tick_age = state.get("market", {}).get("last_tick_age_ms")
        if tick_age is not None and float(tick_age) > 5000:
            checks.append(_check(
                "TICK_FRESH",
                "Market tick freshness",
                "fail",
                f"Last tick {float(tick_age) / 1000:.1f}s ago",
                "Check MT5 MarketWatch and ZeroMQ DATA port",
            ))
        elif tick_age is not None:
            checks.append(_check(
                "TICK_FRESH",
                "Market tick freshness",
                "pass",
                f"Last tick {float(tick_age) / 1000:.1f}s ago",
            ))
    else:
        checks.append(_check(
            "MT5_BRIDGE",
            "MT5 / ZeroMQ bridge",
            "skip",
            f"Simulate mode — bridge check skipped (data_source={resolve_data_source(state)})",
        ))

    try:
        instruments = load_yaml("instruments.yaml").get("instruments", [])
        expected = 15
        count = len([i for i in instruments if i.get("symbol")])
        checks.append(_check(
            "INSTRUMENTS",
            "Competition instruments",
            "pass" if count == expected else "warn",
            f"{count}/{expected} instruments configured",
            None if count == expected else "Verify config/instruments.yaml",
        ))
    except Exception as exc:
        checks.append(_check(
            "INSTRUMENTS",
            "Competition instruments",
            "fail",
            f"Failed to load instruments.yaml: {exc}",
        ))

    dd_tier = str(state.get("risk", {}).get("dd_tier", "normal"))
    checks.append(_check(
        "DRAWDOWN_TIER",
        "Drawdown tier",
        "pass" if dd_tier in ("normal", "elevated") else "warn" if dd_tier == "warning" else "fail",
        f"Tier: {dd_tier}",
        None if dd_tier in ("normal", "elevated", "warning") else "Reduce exposure — emergency tier blocks new risk",
    ))

    discipline = int(state.get("risk", {}).get("discipline", 100))
    checks.append(_check(
        "DISCIPLINE",
        "Risk discipline score",
        "pass" if discipline >= 80 else "warn" if discipline >= 60 else "fail",
        f"{discipline}/100",
        None if discipline >= 80 else "Review risk violations in dashboard",
    ))

    logfire_env = bool(os.getenv("LOGFIRE_TOKEN", "").strip())
    logfire_active = is_logfire_active()
    checks.append(_check(
        "LOGFIRE",
        "Pydantic Logfire",
        "pass" if logfire_active else "warn" if logfire_env else "warn",
        "Tracing active" if logfire_active else (
            "LOGFIRE_TOKEN set but tracing not initialized" if logfire_env else "LOGFIRE_TOKEN not set"
        ),
        None if logfire_active else "export LOGFIRE_TOKEN=… and restart dashboard",
    ))

    notion_on = notion_sync_enabled()
    checks.append(_check(
        "NOTION",
        "Notion sync",
        "pass" if notion_on else "skip",
        "Enabled" if notion_on else "Not configured (optional)",
    ))

    auth = bool(os.getenv("DASHBOARD_AUTH_TOKEN", "").strip())
    checks.append(_check(
        "DASHBOARD_AUTH",
        "Dashboard auth",
        "pass" if auth else "warn",
        "Bearer token configured" if auth else "No DASHBOARD_AUTH_TOKEN — public API",
        None if auth else "Set DASHBOARD_AUTH_TOKEN for Northflank public ingress",
    ))

    dist_ok = Path("frontend/dist/index.html").exists()
    checks.append(_check(
        "FRONTEND_BUILD",
        "Frontend build",
        "pass" if dist_ok else "warn",
        "SPA built" if dist_ok else "frontend/dist missing",
        None if dist_ok else "cd frontend && npm run build",
    ))

    memory_db = Path("data/trade_memory.db")
    checks.append(_check(
        "MEMORY_DB",
        "Trade memory DB",
        "pass" if memory_db.exists() else "warn",
        "data/trade_memory.db present" if memory_db.exists() else "No trade memory yet — episodic layer empty",
    ))

    ai_keys = any(
        os.getenv(k, "").strip()
        for k in ("DOUBLEWORD_API_KEY", "GROQ_API_KEY", "Groq_API_KEY", "ANTHROPIC_API_KEY")
    )
    checks.append(_check(
        "AI_PROVIDERS",
        "AI provider keys",
        "pass" if ai_keys else "warn",
        "At least one provider configured" if ai_keys else "No LLM keys — copilot uses template mode",
    ))

    now = datetime.now(timezone.utc)
    launch_in_sec = max(0.0, (COMPETITION_LAUNCH_UTC - now).total_seconds())
    launched = launch_in_sec <= 0

    blocking = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warn"]
    ready = len(blocking) == 0 and engine_running and (not is_live or mt5)

    return {
        "ready": ready,
        "mode": mode,
        "phase": state.get("phase", "round1"),
        "data_source": resolve_data_source(state),
        "competition_launch_at": COMPETITION_LAUNCH_UTC.isoformat(),
        "launch_in_seconds": launch_in_sec if not launched else 0,
        "launched": launched,
        "summary": {
            "pass": sum(1 for c in checks if c["status"] == "pass"),
            "warn": len(warnings),
            "fail": len(blocking),
            "skip": sum(1 for c in checks if c["status"] == "skip"),
        },
        "checks": checks,
    }
