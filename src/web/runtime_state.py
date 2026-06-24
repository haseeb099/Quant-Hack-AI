"""Read/write runtime state snapshot for dashboard."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_PATH = Path("data/runtime_state.json")
MAX_EQUITY_HISTORY = 500
_lock = threading.Lock()


def default_state() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "phase": "round1",
        "mode": "simulate",
        "timestamp": now,
        "last_cycle_at": None,
        "next_cycle_at": None,
        "connected": False,
        "engine_running": False,
        "engine_paused": False,
        "cycle_in_progress": False,
        "mt5_connected": False,
        "zmq_last_error": None,
        "account": {
            "equity": None,
            "balance": None,
            "margin": 0,
            "free_margin": None,
            "gross_exposure": 0,
            "initial_equity": None,
            "equity_available": False,
        },
        "positions": [],
        "risk": {
            "dd_tier": "normal",
            "drawdown_pct": 0.0,
            "sharpe": 0.0,
            "discipline": 100,
            "margin_state": "normal",
            "margin_usage_pct": 0.0,
            "effective_leverage": 0.0,
            "concentration_pct": 0.0,
            "violations": [],
        },
        "last_cycle": {
            "symbols_processed": 0,
            "symbols_attempted": 0,
            "decisions": [],
            "agent_votes": [],
        },
        "equity_history": [],
        "instruments": {},
        "market": {
            "last_tick_at": None,
            "last_tick_age_ms": None,
        },
        "risk_events": [],
    }


def read_state(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path if path is not None else STATE_PATH)
    if not p.exists():
        return default_state()
    try:
        with _lock:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        base = default_state()
        base.update(data)
        return base
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read runtime state: %s", exc)
        return default_state()


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


def write_state(state: dict[str, Any], path: Path | str = STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)


def append_equity_point(
    state: dict[str, Any],
    equity: float | None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if equity is None or equity <= 0:
        return state
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    history = state.setdefault("equity_history", [])
    if history:
        last = history[-1].get("equity")
        if last and last > 0:
            ratio = equity / float(last)
            if ratio > 100 or ratio < 0.01:
                return state
    history.append({"t": ts, "equity": equity})
    if len(history) > MAX_EQUITY_HISTORY:
        state["equity_history"] = history[-MAX_EQUITY_HISTORY:]
    return state


def append_risk_event(
    state: dict[str, Any],
    event_type: str,
    message: str,
    severity: str = "warning",
) -> dict[str, Any]:
    events = state.setdefault("risk_events", [])
    events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "message": message,
        "severity": severity,
    })
    if len(events) > 100:
        state["risk_events"] = events[-100:]
    return state
