"""Status and account endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from src.utils.logger import instrument_span
from src.web.routes._helpers import is_state_stale, resolve_data_source, state_age_seconds
from src.web.runtime_state import read_state

router = APIRouter(tags=["status"])


def _compute_tick_age_ms(market: dict) -> float | None:
    """Return tick age from cached ms or compute from last_tick_at timestamp."""
    age = market.get("last_tick_age_ms")
    if age is not None:
        return float(age)
    last_at = market.get("last_tick_at")
    if not last_at:
        return None
    try:
        tick_at = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - tick_at).total_seconds() * 1000)
    except ValueError:
        return None


@router.get("/api/status")
@instrument_span("quantai.status.summary")
def get_status() -> dict:
    state = read_state()
    mode = state.get("mode", "simulate")
    engine_running = state.get("engine_running", False)
    mt5_connected = state.get("mt5_connected", state.get("connected", False))
    market = state.get("market", {})
    tick_age_ms = _compute_tick_age_ms(market)
    connected = bool(engine_running and (mode != "live" or mt5_connected))
    data_source = resolve_data_source(state)
    age_sec = state_age_seconds(state)
    engine_cfg = state.get("engine_config") or {}
    account = state.get("account") or {}
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
        "last_tick_age_ms": tick_age_ms,
        "account_profile": state.get("account_profile"),
        "cycle_minutes": engine_cfg.get("cycle_minutes"),
        "session_symbol_filter": engine_cfg.get("session_symbol_filter"),
        "round_equity_baseline": engine_cfg.get("round_equity_baseline"),
        "initial_equity": account.get("initial_equity"),
        "bridge": engine_cfg.get("bridge"),
        "blocked_symbols": engine_cfg.get("blocked_symbols") or [],
    }


@router.get("/api/health/engine")
@instrument_span("quantai.status.engine_health")
def get_engine_health() -> dict:
    state = read_state()
    risk = state.get("risk", {})
    market = state.get("market", {})
    tick_age_ms = _compute_tick_age_ms(market)
    engine_cfg = state.get("engine_config") or {}
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
        "last_tick_age_ms": tick_age_ms,
        "dd_tier": risk.get("dd_tier"),
        "drawdown_pct": risk.get("drawdown_pct"),
        "discipline": risk.get("discipline"),
        "risk_events": state.get("risk_events", [])[-5:],
        "account_profile": state.get("account_profile"),
        "engine_config": engine_cfg,
    }


@router.get("/api/account")
@instrument_span("quantai.status.account")
def get_account() -> dict:
    state = read_state()
    account = state.get("account", {})
    equity_raw = account.get("equity")
    initial_raw = account.get("initial_equity")
    equity = float(equity_raw) if equity_raw is not None else 0.0
    initial = float(initial_raw) if initial_raw is not None else equity
    balance_raw = account.get("balance")
    balance = float(balance_raw) if balance_raw is not None else None
    account_stale = bool(account.get("account_stale"))
    equity_available = account.get("equity_available", not account_stale)
    daily_pnl = None
    if balance is not None and equity_available and not account_stale:
        daily_pnl = equity - balance
    return {
        **account,
        "return_pct": ((equity - initial) / initial * 100) if initial and equity_available else 0.0,
        "daily_pnl": daily_pnl,
    }


@router.get("/api/equity-curve")
@instrument_span("quantai.status.equity_curve")
def get_equity_curve() -> dict:
    state = read_state()
    return {"history": state.get("equity_history", [])}
