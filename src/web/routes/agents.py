"""Agent performance endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["agents"])

AGENT_NAMES = [
    "trend_surfer",
    "breakout_hunter",
    "momentum_pulse",
    "mean_reversion",
    "sentiment_agent",
    "ml_signal",
]
AGENT_LABELS = {
    "trend_surfer": "TrendSurfer",
    "breakout_hunter": "BreakoutHunter",
    "momentum_pulse": "MomentumPulse",
    "mean_reversion": "MeanReversion",
    "sentiment_agent": "SentimentAgent",
    "ml_signal": "ML Signal",
}


def _flatten_agent_votes(votes: list) -> list[dict]:
    """Expand nested {symbol, votes: [...]} into flat vote dicts with symbol on each."""
    flat: list[dict] = []
    for item in votes:
        if not isinstance(item, dict):
            continue
        nested = item.get("votes")
        if isinstance(nested, list):
            symbol = item.get("symbol")
            for vote in nested:
                if isinstance(vote, dict):
                    flat.append({**vote, "symbol": vote.get("symbol", symbol)})
            continue
        flat.append(item)
    return flat


def _agent_stats() -> list[dict]:
    try:
        from src.learning.layered_memory import LayeredMemory
        memory = LayeredMemory()
        return [
            {
                "agent": name,
                "label": AGENT_LABELS.get(name, name),
                **memory.agent_performance(name),
            }
            for name in AGENT_NAMES
        ]
    except Exception:
        return [
            {"agent": n, "label": AGENT_LABELS.get(n, n), "win_rate": None, "avg_r": 0.0, "sample_size": 0}
            for n in AGENT_NAMES
        ]


@router.get("/api/agents/health")
def get_agent_health() -> dict:
    try:
        from src.operator.agent_health import load_agent_health, run_agent_health

        report = load_agent_health()
        if not report:
            report = run_agent_health(persist=True)
        return report
    except Exception as exc:
        return {"status": "RED", "error": str(exc), "agents": {}}


@router.get("/api/agents/audit")
def get_agent_audit() -> dict:
    try:
        from src.learning.agent_audit import load_agent_audit, run_agent_audit

        report = load_agent_audit()
        if not report:
            report = run_agent_audit(persist=True)
        return report
    except Exception as exc:
        return {"error": str(exc), "agents": {}, "recommendations": []}


@router.get("/api/agents/tuned-config")
def get_tuned_config() -> dict:
    path = Path("data/agents_tuned.yaml")
    plan_path = Path("data/adaptation_plan.json")
    plan = None
    if plan_path.exists():
        try:
            with open(plan_path, encoding="utf-8") as f:
                plan = json.load(f)
        except (json.JSONDecodeError, OSError):
            plan = None
    tuned_exists = path.exists()
    tuned_text = path.read_text(encoding="utf-8") if tuned_exists else None
    return {
        "exists": tuned_exists,
        "path": str(path),
        "yaml": tuned_text,
        "plan": plan,
    }


@router.get("/api/agents")
def get_agents() -> dict:
    return {"agents": _agent_stats()}


@router.get("/api/agents/attribution")
def get_agent_attribution() -> dict:
    """Per-agent trade attribution from layered memory."""
    try:
        from src.learning.layered_memory import LayeredMemory

        memory = LayeredMemory()
        working = memory.get_working_memory()
        by_agent: dict[str, dict] = {}
        for trade in working:
            agent = trade.agent
            bucket = by_agent.setdefault(
                agent,
                {"agent": agent, "trades": 0, "wins": 0, "total_r": 0.0, "symbols": set()},
            )
            bucket["trades"] += 1
            r = float(trade.r_multiple or 0)
            bucket["total_r"] += r
            if r > 0:
                bucket["wins"] += 1
            bucket["symbols"].add(trade.symbol)
        rows = []
        for agent, data in by_agent.items():
            n = data["trades"]
            rows.append({
                "agent": agent,
                "label": AGENT_LABELS.get(agent, agent),
                "trades": n,
                "win_rate": data["wins"] / n if n else 0.0,
                "avg_r": data["total_r"] / n if n else 0.0,
                "symbols": sorted(s for s in data["symbols"] if s),
            })
        return {"attribution": rows, "total_closed_trades": len(working)}
    except Exception:
        return {"attribution": [], "total_closed_trades": 0}


@router.get("/api/agents/last-cycle")
def get_last_cycle_votes() -> dict:
    state = read_state()
    last_cycle = state.get("last_cycle", {})
    return {
        "symbols_processed": last_cycle.get("symbols_processed", 0),
        "symbols_attempted": last_cycle.get("symbols_attempted", 0),
        "decisions": last_cycle.get("decisions", []),
        "agent_votes": _flatten_agent_votes(last_cycle.get("agent_votes", [])),
        "last_cycle_at": state.get("last_cycle_at"),
    }
