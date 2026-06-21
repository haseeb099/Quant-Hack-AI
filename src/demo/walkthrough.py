"""5-minute demo walkthrough for technology prize judges."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from src.utils.logger import is_logfire_active

StepStatus = Literal["pass", "warn", "fail", "manual"]

_DEMO_STEPS: list[dict[str, Any]] = [
    {
        "id": "architecture",
        "order": 1,
        "title": "Architecture Overview",
        "duration_sec": 45,
        "narration": (
            "QuantAI is a regime-aware multi-agent trading system. Four specialized agents "
            "generate signals, a Claude-powered MetaOrchestrator resolves conflicts, deterministic "
            "risk rails enforce the constitution, and offline self-learning adapts weights between rounds."
        ),
        "dashboard_route": "/",
        "doc_path": "docs/architecture.md",
        "command": None,
        "check": "architecture",
    },
    {
        "id": "logfire_trace",
        "order": 2,
        "title": "Live Decision Cycle — Logfire Trace",
        "duration_sec": 60,
        "narration": (
            "Every decision is fully traced. Run one complete cycle in Logfire — from market data "
            "ingestion through feature computation to the final orchestrator call."
        ),
        "dashboard_route": "/decisions",
        "doc_path": None,
        "command": "python main.py --mode single-cycle --phase round1",
        "check": "logfire",
    },
    {
        "id": "pipeline",
        "order": 3,
        "title": "Signals → Orchestrator → Risk → Execution",
        "duration_sec": 90,
        "narration": (
            "Watch the pipeline: four agents vote on each symbol. When confidence exceeds the gate, "
            "Claude receives full context including regime, session, and layered memory. The decision "
            "passes through Kelly sizing, drawdown tiers, and margin monitoring before ZeroMQ sends the order."
        ),
        "dashboard_route": "/agents",
        "doc_path": "logs/trades.jsonl",
        "command": None,
        "check": "pipeline",
    },
    {
        "id": "memory_learning",
        "order": 4,
        "title": "Trade Memory & Offline Learning",
        "duration_sec": 60,
        "narration": (
            "Closed trades feed three memory layers — working, episodic, and semantic. Between rounds, "
            "adapt_round.py rebuilds semantic weights with walk-forward validation. Weight shifts are "
            "capped at ±10% per round."
        ),
        "dashboard_route": "/agents",
        "doc_path": "data/trade_memory.db",
        "command": "python scripts/adapt_round.py --phase round1",
        "check": "memory",
    },
    {
        "id": "risk_constitution",
        "order": 5,
        "title": "Risk Constitution & Compliance",
        "duration_sec": 45,
        "narration": (
            "Risk parameters are frozen — the learning loop never touches them. Five drawdown tiers "
            "from normal to emergency close-all at 15%. Compliance heartbeat tracks sustained violations."
        ),
        "dashboard_route": "/risk",
        "doc_path": "config/risk.yaml",
        "command": None,
        "check": "risk",
    },
    {
        "id": "sponsors",
        "order": 6,
        "title": "Sponsor Technologies",
        "duration_sec": 30,
        "narration": (
            "Built with Anthropic Claude for orchestration, Pydantic Logfire for observability, "
            "Doubleword for optional inference routing, and Northflank for the live monitoring dashboard."
        ),
        "dashboard_route": "/",
        "doc_path": "docs/sponsor_integrations.md",
        "command": "./scripts/start_dashboard.sh",
        "check": "sponsors",
    },
]


def _step_check(check: str) -> tuple[StepStatus, str]:
    if check == "architecture":
        ok = Path("docs/architecture.md").is_file()
        return ("pass" if ok else "fail"), "Architecture documentation ready" if ok else "docs/architecture.md missing"

    if check == "logfire":
        if is_logfire_active():
            return "pass", "Logfire tracing active"
        if os.getenv("LOGFIRE_TOKEN"):
            return "warn", "LOGFIRE_TOKEN set — restart engine to activate"
        return "warn", "Run with LOGFIRE_TOKEN for live trace demo"

    if check == "pipeline":
        agents = Path("src/agents")
        engine = Path("src/engine/trading_engine.py")
        bridge = Path("src/bridges/zeromq_connector.py")
        ok = agents.is_dir() and engine.is_file() and bridge.is_file()
        return ("pass" if ok else "fail"), "Full pipeline modules present" if ok else "Missing agent/engine/bridge"

    if check == "memory":
        memory = Path("src/learning/layered_memory.py")
        adapt = Path("scripts/adapt_round.py")
        db = Path("data/trade_memory.db")
        detail = "Layered memory + adapt_round ready"
        if db.is_file():
            detail += " (trade_memory.db exists)"
        ok = memory.is_file() and adapt.is_file()
        return ("pass" if ok else "fail"), detail if ok else "Memory/adapt scripts missing"

    if check == "risk":
        risk = Path("src/risk/drawdown_guard.py")
        config = Path("config/risk.yaml")
        ok = risk.is_file() and config.is_file()
        return ("pass" if ok else "warn"), "Risk constitution modules ready" if ok else "Risk config incomplete"

    if check == "sponsors":
        sponsors_doc = Path("docs/sponsor_integrations.md")
        dashboard = Path("src/web/app.py").is_file()
        ok = sponsors_doc.is_file() and dashboard
        return ("pass" if ok else "fail"), "Sponsor integrations documented" if ok else "Sponsor docs missing"

    return "manual", "Operator verifies"


def build_demo_walkthrough() -> dict[str, Any]:
    steps_out: list[dict[str, Any]] = []
    for step in _DEMO_STEPS:
        status, detail = _step_check(step["check"])
        doc_exists = bool(step.get("doc_path") and Path(step["doc_path"]).exists())
        steps_out.append({
            **step,
            "status": status,
            "detail": detail,
            "doc_available": doc_exists,
        })

    passed = sum(1 for s in steps_out if s["status"] == "pass")
    total_duration = sum(s["duration_sec"] for s in steps_out)

    return {
        "title": "QuantAI Demo Walkthrough",
        "audience": "Technology prize judges",
        "duration_sec": total_duration,
        "duration_label": f"{total_duration // 60} min",
        "closing_line": (
            "QuantAI: deterministic risk rails, bounded self-learning, auditable AI orchestration — "
            "ready for 24-hour unattended competition deployment."
        ),
        "steps": steps_out,
        "summary": {
            "pass": passed,
            "total": len(steps_out),
            "ready": passed >= 4,
        },
        "docs": "docs/demo_script.md",
    }
