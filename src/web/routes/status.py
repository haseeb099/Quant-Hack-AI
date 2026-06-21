"""Status and account endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["status"])


@router.get("/api/status")
def get_status() -> dict:
    state = read_state()
    mode = state.get("mode", "simulate")
    engine_running = state.get("engine_running", False)
    mt5_connected = state.get("mt5_connected", state.get("connected", False))
    market = state.get("market", {})
    connected = bool(engine_running and (mode != "live" or mt5_connected))
    return {
        "phase": state.get("phase", "round1"),
        "mode": mode,
        "last_cycle_at": state.get("last_cycle_at"),
        "next_cycle_at": state.get("next_cycle_at"),
        "connected": connected,
        "engine_running": engine_running,
        "engine_paused": state.get("engine_paused", False),
        "cycle_in_progress": state.get("cycle_in_progress", False),
        "mt5_connected": mt5_connected,
        "timestamp": state.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "zmq_last_error": state.get("zmq_last_error"),
        "last_tick_at": market.get("last_tick_at"),
        "last_tick_age_ms": market.get("last_tick_age_ms"),
    }


@router.get("/api/account")
def get_account() -> dict:
    state = read_state()
    account = state.get("account", {})
    equity = float(account.get("equity", 1_000_000))
    initial = float(account.get("initial_equity", 1_000_000))
    return {
        **account,
        "return_pct": ((equity - initial) / initial * 100) if initial else 0.0,
        "daily_pnl": equity - float(account.get("balance", equity)),
    }


@router.get("/api/equity-curve")
def get_equity_curve() -> dict:
    state = read_state()
    return {"history": state.get("equity_history", [])}
