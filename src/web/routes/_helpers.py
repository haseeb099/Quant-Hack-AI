"""Shared helpers for dashboard API routes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

COMPETITION_WEIGHTS = {
    "return": 0.70,
    "drawdown": 0.15,
    "sharpe": 0.10,
    "discipline": 0.05,
}


def resolve_data_source(state: dict[str, Any]) -> str:
    """Classify dashboard data origin: demo, simulate, or live."""
    if os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        return "demo"
    mode = str(state.get("mode", "simulate"))
    engine_running = bool(state.get("engine_running", False))
    if mode == "live" and state.get("mt5_connected"):
        return "live"
    if engine_running and mode == "simulate":
        return "simulate"
    if not engine_running:
        return "demo"
    return mode


def state_age_seconds(state: dict[str, Any]) -> float | None:
    ts = state.get("timestamp")
    if not ts:
        return None
    try:
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - when).total_seconds())
    except ValueError:
        return None


def is_state_stale(state: dict[str, Any], max_age_sec: float = 60.0) -> bool:
    if not state.get("engine_running"):
        return False
    age = state_age_seconds(state)
    return age is not None and age > max_age_sec


def compute_competition_score(state: dict[str, Any]) -> dict[str, Any]:
    account = state.get("account", {})
    risk = state.get("risk", {})
    equity_raw = account.get("equity")
    initial_raw = account.get("initial_equity")
    equity = float(equity_raw) if equity_raw is not None else 0.0
    # Round-local baseline: phase-reset value or official $1M platform baseline.
    if initial_raw is not None:
        initial = float(initial_raw)
    elif equity > 0:
        initial = equity
    else:
        initial = 1_000_000.0
    if initial <= 0:
        initial = 1_000_000.0
    return_pct = ((equity - initial) / initial * 100) if initial else 0.0
    drawdown_pct = float(risk.get("drawdown_pct", 0))
    sharpe = float(risk.get("sharpe", 0))
    discipline = float(risk.get("discipline", 100))

    components = [
        {
            "label": "Return",
            "weight": COMPETITION_WEIGHTS["return"],
            "value": min(100.0, max(0.0, (return_pct / 30.0) * 100)),
            "raw": return_pct,
        },
        {
            "label": "Drawdown",
            "weight": COMPETITION_WEIGHTS["drawdown"],
            "value": min(100.0, max(0.0, 100.0 - (drawdown_pct / 0.15) * 100)),
            "raw": drawdown_pct,
        },
        {
            "label": "Sharpe",
            "weight": COMPETITION_WEIGHTS["sharpe"],
            "value": min(100.0, max(0.0, sharpe * 25)),
            "raw": sharpe,
        },
        {
            "label": "Risk Discipline",
            "weight": COMPETITION_WEIGHTS["discipline"],
            "value": min(100.0, max(0.0, discipline)),
            "raw": discipline,
        },
    ]
    total = sum(c["value"] * c["weight"] for c in components)
    return {
        "total": round(total, 2),
        "components": components,
        "weights": COMPETITION_WEIGHTS,
        "initial_equity": initial,
        "return_pct": round(return_pct, 4),
        "note": "Rank percentiles require external leaderboard API",
    }
