"""Status and account endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["status"])


@router.get("/api/status")
def get_status() -> dict:
    state = read_state()
    engine_running = state.get("engine_running", False)
    mt5_connected = state.get("mt5_connected", state.get("connected", False))
    return {
        "phase": state.get("phase", "round1"),
        "mode": state.get("mode", "simulate"),
        "last_cycle_at": state.get("last_cycle_at"),
        "next_cycle_at": state.get("next_cycle_at"),
        "connected": bool(engine_running and mt5_connected),
        "engine_running": engine_running,
        "mt5_connected": mt5_connected,
        "timestamp": state.get("timestamp", datetime.now(timezone.utc).isoformat()),
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
