"""Agent performance endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["agents"])

AGENT_NAMES = ["trend_surfer", "breakout_hunter", "momentum_pulse", "mean_reversion"]
AGENT_LABELS = {
    "trend_surfer": "TrendSurfer",
    "breakout_hunter": "BreakoutHunter",
    "momentum_pulse": "MomentumPulse",
    "mean_reversion": "MeanReversion",
}


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
            {"agent": n, "label": AGENT_LABELS.get(n, n), "win_rate": 0.5, "avg_r": 0.0, "sample_size": 0}
            for n in AGENT_NAMES
        ]


@router.get("/api/agents")
def get_agents() -> dict:
    return {"agents": _agent_stats()}


@router.get("/api/agents/last-cycle")
def get_last_cycle_votes() -> dict:
    state = read_state()
    last_cycle = state.get("last_cycle", {})
    return {
        "symbols_processed": last_cycle.get("symbols_processed", 0),
        "decisions": last_cycle.get("decisions", []),
        "agent_votes": last_cycle.get("agent_votes", []),
        "last_cycle_at": state.get("last_cycle_at"),
    }
