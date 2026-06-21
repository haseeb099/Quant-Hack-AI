"""Competition-day operator runbook — phased checklist with auto status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.operator.preflight import run_preflight
from src.operator.verification_store import read_verification_state
from src.web.between_round import is_scheduled_adaptation_window
from src.web.launch_readiness import evaluate_launch_readiness
from src.web.runtime_state import read_state

_BST = ZoneInfo("Europe/London")

# Phased operator steps for 24h competition deployment
_RUNBOOK_PHASES: list[dict[str, Any]] = [
    {
        "id": "pre_launch",
        "title": "Pre-launch (T-24h)",
        "steps": [
            {"id": "pytest", "label": "Run pytest suite", "check": "preflight_pytest"},
            {"id": "mt5", "label": "MT5 + ZeroMQ bridge online", "check": "tick_stream"},
            {"id": "docker", "label": "Docker images buildable", "check": "dockerfiles"},
            {"id": "auth", "label": "Dashboard auth for Northflank", "check": "dashboard_auth"},
        ],
    },
    {
        "id": "launch",
        "title": "Competition launch",
        "steps": [
            {"id": "engine", "label": "Engine running live", "check": "engine_running"},
            {"id": "bridge", "label": "MT5 bridge connected", "check": "mt5_bridge"},
            {"id": "ticks", "label": "Fresh market ticks", "check": "tick_fresh"},
            {"id": "launch_ready", "label": "Launch readiness GO", "check": "launch_ready"},
        ],
    },
    {
        "id": "during_round",
        "title": "During round (24h)",
        "steps": [
            {"id": "monitor", "label": "Dashboard + Logfire monitoring", "check": "logfire"},
            {"id": "risk", "label": "Drawdown tier normal/warning", "check": "drawdown_ok"},
            {"id": "discipline", "label": "Risk discipline ≥80", "check": "discipline_ok"},
            {"id": "copilot", "label": "Copilot grounded analysis available", "check": "copilot"},
        ],
    },
    {
        "id": "between_rounds",
        "title": "Between rounds (22:00–23:00 BST)",
        "steps": [
            {"id": "pause", "label": "Pause engine or confirm window", "check": "adapt_window"},
            {"id": "adapt", "label": "Run adapt_round / dashboard adaptation", "check": "adaptation_allowed"},
            {"id": "learning", "label": "Learning pipeline (ingest + regime)", "check": "learning_pipeline"},
            {"id": "notion", "label": "Sync results to Notion", "check": "notion"},
        ],
    },
]


def _verification_map() -> dict[str, dict[str, Any]]:
    cached = read_verification_state()
    return {c["code"]: c for c in cached.get("checks", [])}


def _step_status(check: str, state: dict[str, Any], preflight: dict[str, Any], launch: dict[str, Any]) -> tuple[str, str]:
    """Return (status, detail) — pass | warn | fail | manual."""
    if check == "always":
        return "manual", "Operator verifies"

    preflight_map = {c["code"]: c for c in preflight.get("checks", [])}
    verification_map = _verification_map()

    if check == "preflight_pytest":
        c = verification_map.get("PYTEST")
        if c:
            return ("pass" if c["passed"] else "fail"), c.get("detail", "")
        return "manual", "Run POST /api/operator/verification/run or pytest tests/ -q"

    if check == "copilot":
        c = verification_map.get("COPILOT")
        if c:
            return ("pass" if c["passed"] else "fail"), c.get("detail", "")
        return "manual", "Run automated verification"

    if check == "learning_pipeline":
        c = verification_map.get("LEARNING_PIPELINE")
        if c:
            return ("pass" if c["passed"] else "warn"), c.get("detail", "")
        return "manual", "Run scripts/run_learning_pipeline.sh between rounds"

    if check == "tick_stream":
        c = preflight_map.get("TICK_STREAM")
        if c:
            return ("pass" if c["passed"] else "fail"), c.get("detail", "")
        return "manual", "Run scripts/preflight_competition.py"

    if check == "dockerfiles":
        c = preflight_map.get("DOCKERFILES")
        if c:
            return ("pass" if c["passed"] else "fail"), c.get("detail", "")
        return "fail", "Dockerfiles missing"

    if check == "dashboard_auth":
        c = preflight_map.get("DASHBOARD_AUTH")
        if c and c["passed"]:
            return "pass", c.get("detail", "")
        return "warn", "Set DASHBOARD_AUTH_TOKEN for production"

    if check == "engine_running":
        ok = bool(state.get("engine_running"))
        return ("pass" if ok else "fail"), "Engine running" if ok else "Start engine"

    if check == "mt5_bridge":
        if state.get("mode") != "live":
            return "warn", "Simulate mode — bridge optional"
        ok = bool(state.get("mt5_connected"))
        return ("pass" if ok else "fail"), "MT5 connected" if ok else "Bridge offline"

    if check == "tick_fresh":
        age = state.get("market", {}).get("last_tick_age_ms")
        if age is None:
            return "warn", "No tick age in state"
        ok = float(age) < 5000
        return ("pass" if ok else "fail"), f"tick age {float(age) / 1000:.1f}s"

    if check == "launch_ready":
        ok = launch.get("ready", False)
        return ("pass" if ok else "warn"), f"{launch.get('summary', {})}"

    if check == "logfire":
        import os
        from src.utils.logger import is_logfire_active
        if is_logfire_active():
            return "pass", "Logfire tracing active"
        if os.getenv("LOGFIRE_TOKEN"):
            return "warn", "Token set — restart to activate"
        return "warn", "LOGFIRE_TOKEN not set"

    if check == "drawdown_ok":
        tier = str(state.get("risk", {}).get("dd_tier", "normal"))
        ok = tier in ("normal", "elevated", "warning")
        return ("pass" if ok else "fail"), f"dd_tier={tier}"

    if check == "discipline_ok":
        d = int(state.get("risk", {}).get("discipline", 100))
        ok = d >= 80
        return ("pass" if ok else "warn"), f"discipline={d}"

    if check == "adapt_window":
        if is_scheduled_adaptation_window():
            return "pass", "Adaptation window open"
        return "warn", "Outside 22:00–23:00 BST window"

    if check == "adaptation_allowed":
        from src.web.between_round import can_run_adaptation
        ok, reason = can_run_adaptation(state)
        return ("pass" if ok else "warn"), reason

    if check == "notion":
        from src.integrations.notion_sync import notion_sync_enabled
        ok = notion_sync_enabled()
        return ("pass" if ok else "warn"), "Notion enabled" if ok else "Optional — not configured"

    return "manual", ""


def build_operator_runbook(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or read_state()
    preflight = run_preflight(zmq_only=True)
    launch = evaluate_launch_readiness(state)
    now = datetime.now(timezone.utc).astimezone(_BST)

    phases: list[dict[str, Any]] = []
    for phase in _RUNBOOK_PHASES:
        steps_out = []
        for step in phase["steps"]:
            status, detail = _step_status(step["check"], state, preflight, launch)
            steps_out.append({
                **step,
                "status": status,
                "detail": detail,
            })
        passed = sum(1 for s in steps_out if s["status"] == "pass")
        phases.append({
            "id": phase["id"],
            "title": phase["title"],
            "steps": steps_out,
            "summary": {"pass": passed, "total": len(steps_out)},
        })

    return {
        "timestamp_bst": now.isoformat(),
        "phase": state.get("phase", "round1"),
        "mode": state.get("mode", "simulate"),
        "preflight": preflight,
        "launch_readiness": launch.get("ready"),
        "phases": phases,
    }


def northflank_deploy_status() -> dict[str, Any]:
    """Northflank-specific deploy checklist."""
    import os

    preflight = run_preflight(zmq_only=True)
    checks = {c["code"]: c for c in preflight["checks"]}
    env_vars = {
        "DASHBOARD_AUTH_TOKEN": bool(os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()),
        "LOGFIRE_TOKEN": bool(os.getenv("LOGFIRE_TOKEN", "").strip()),
        "ZMQ_HOST": bool(os.getenv("ZMQ_HOST", "").strip()),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "DOUBLEWORD_API_KEY": bool(os.getenv("DOUBLEWORD_API_KEY", "").strip()),
    }
    return {
        "platform": "northflank",
        "services": [
            {
                "name": "quantai-engine",
                "dockerfile": "Dockerfile.engine",
                "ready": checks.get("DOCKERFILES", {}).get("passed", False),
                "volume_mounts": ["/app/logs", "/app/data"],
                "public": False,
            },
            {
                "name": "quantai-dashboard",
                "dockerfile": "Dockerfile.dashboard",
                "ready": checks.get("DOCKERFILES", {}).get("passed", False)
                and checks.get("FRONTEND_BUILD", {}).get("passed", False),
                "volume_mounts": ["/app/logs", "/app/data"],
                "public": True,
                "port": int(os.getenv("PORT", "8080")),
            },
        ],
        "env_configured": env_vars,
        "smoke_commands": [
            "docker build -f Dockerfile.dashboard -t quantai-dashboard .",
            "docker build -f Dockerfile.engine -t quantai-engine .",
            "./scripts/deploy_smoke.sh",
        ],
        "docs": "docs/northflank_deploy.md",
        "preflight": preflight,
    }
