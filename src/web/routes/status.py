"""Status and account endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from src.web.routes._helpers import is_state_stale, resolve_data_source, state_age_seconds
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
    data_source = resolve_data_source(state)
    age_sec = state_age_seconds(state)
    return {
        "phase": state.get("phase", "round1"),
        "mode": mode,
        "data_source": data_source,
        "state_age_sec": age_sec,
        "state_stale": is_state_stale(state),
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
        "account_profile": state.get("account_profile"),
    }


@router.get("/api/health/engine")
def get_engine_health() -> dict:
    state = read_state()
    risk = state.get("risk", {})
    market = state.get("market", {})
    return {
        "data_source": resolve_data_source(state),
        "state_stale": is_state_stale(state),
        "state_age_sec": state_age_seconds(state),
        "engine_running": state.get("engine_running", False),
        "engine_paused": state.get("engine_paused", False),
        "cycle_in_progress": state.get("cycle_in_progress", False),
        "mode": state.get("mode", "simulate"),
        "mt5_connected": state.get("mt5_connected", False),
        "zmq_last_error": state.get("zmq_last_error"),
        "last_cycle_at": state.get("last_cycle_at"),
        "next_cycle_at": state.get("next_cycle_at"),
        "last_tick_at": market.get("last_tick_at"),
        "last_tick_age_ms": market.get("last_tick_age_ms"),
        "dd_tier": risk.get("dd_tier"),
        "drawdown_pct": risk.get("drawdown_pct"),
        "discipline": risk.get("discipline"),
        "risk_events": state.get("risk_events", [])[-5:],
        "account_profile": state.get("account_profile"),
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
