"""Publish engine state to runtime_state.json for dashboard consumption."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.web.runtime_state import (
    STATE_PATH,
    append_equity_point,
    append_risk_event,
    read_state,
    write_state,
)

logger = logging.getLogger(__name__)

_listeners: list[Any] = []
_tick_listeners: list[Any] = []
_alert_listeners: list[Any] = []


def register_state_listener(callback: Any) -> None:
    """Register callback invoked when runtime state is published."""
    if callback not in _listeners:
        _listeners.append(callback)


def register_tick_listener(callback: Any) -> None:
    if callback not in _tick_listeners:
        _tick_listeners.append(callback)


def register_alert_listener(callback: Any) -> None:
    if callback not in _alert_listeners:
        _alert_listeners.append(callback)


def _notify_listeners(state: dict[str, Any]) -> None:
    for listener in _listeners:
        try:
            listener(state)
        except Exception:
            logger.debug("State listener failed", exc_info=True)


def notify_ticks(payload: dict[str, Any]) -> None:
    for listener in _tick_listeners:
        try:
            listener(payload)
        except Exception:
            logger.debug("Tick listener failed", exc_info=True)


def notify_market_alert(payload: dict[str, Any]) -> None:
    for listener in _alert_listeners:
        try:
            listener(payload)
        except Exception:
            logger.debug("Alert listener failed", exc_info=True)


def _classify_skip_reason(reason: str) -> str:
    """Bucket skip reasons for dashboard clarity (operational vs data failure)."""
    if reason.startswith("Live filter:"):
        return "blocked"
    if reason.startswith("Net directional"):
        return "net_directional"
    if "Insufficient OHLCV" in reason or "OHLCV" in reason and "Insufficient" in reason:
        return "data_failure"
    if reason.startswith("Session inactive"):
        return "session"
    if "Open position already exists" in reason:
        return "open_position"
    if "Symbol cooldown" in reason:
        return "cooldown"
    if reason == "HOLD decision":
        return "hold"
    if "blocked" in reason.lower() or "Blocked" in reason:
        return "blocked"
    return "other"


def _skip_reason_map(last_cycle: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Map symbol -> skip reason and category from last cycle decisions."""
    out: dict[str, dict[str, str]] = {}
    for decision in last_cycle.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        if decision.get("status") != "skipped":
            continue
        symbol = str(decision.get("symbol") or "")
        if not symbol:
            continue
        reason = str(decision.get("skip_reason") or decision.get("reasoning") or "")
        out[symbol] = {
            "cycle_skip_reason": reason,
            "skip_category": _classify_skip_reason(reason),
        }
    return out


def _normalize_instrument_health(data: dict[str, Any]) -> dict[str, Any]:
    """Green when ticks are fresh; amber only for stale ticks or missing tick+bar."""
    tick_age = data.get("tick_age_ms")
    last_close = data.get("last_close")
    health = "red"
    if tick_age is not None and float(tick_age) < 2000:
        health = "green"
    elif tick_age is not None and float(tick_age) < 5000:
        health = "amber"
    elif last_close is not None:
        health = "amber"
    data = {**data, "health": health, "market_health": health}
    return data


def _phase_blocked_symbols(phase: str) -> list[str]:
    try:
        from src.engine.config import load_yaml

        phases = load_yaml("phases.yaml").get("phases", {})
        rules = phases.get(phase, {}) if isinstance(phases, dict) else {}
        blocked = rules.get("blocked_symbols", [])
        return [str(s) for s in blocked] if isinstance(blocked, list) else []
    except Exception:
        return []


def _enrich_instruments(
    instruments: dict[str, Any],
    last_cycle: dict[str, Any] | None,
) -> dict[str, Any]:
    skips = _skip_reason_map(last_cycle or {})
    enriched: dict[str, Any] = {}
    for sym, raw in instruments.items():
        data = _normalize_instrument_health(dict(raw))
        if sym in skips:
            data.update(skips[sym])
        enriched[sym] = data
    return enriched


def _merge_instruments(
    state: dict[str, Any],
    instruments: dict[str, Any],
    *,
    last_cycle: dict[str, Any] | None = None,
) -> None:
    existing = state.setdefault("instruments", {})
    enriched = _enrich_instruments(instruments, last_cycle)
    for sym, data in enriched.items():
        existing[sym] = {**existing.get(sym, {}), **data}


def update_live_market(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge live tick data into runtime state without a full engine snapshot."""
    state = read_state()
    instruments = payload.get("instruments", {})
    if instruments:
        _merge_instruments(state, instruments, last_cycle=state.get("last_cycle"))
        # Re-normalize health for all known instruments when ticks refresh
        existing = state.get("instruments", {})
        state["instruments"] = _enrich_instruments(existing, state.get("last_cycle"))
    state["market"] = {
        "last_tick_at": payload.get("last_tick_at"),
        "last_tick_age_ms": payload.get("last_tick_age_ms"),
    }
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_state(state, STATE_PATH)
    return state


class StatePublisher:
    """Writes dashboard snapshots after each engine cycle and risk events."""

    def __init__(self, state_path: str | None = None, cycle_minutes: int = 15) -> None:
        self.state_path = state_path or str(STATE_PATH)
        self.cycle_minutes = cycle_minutes

    def publish(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Write a full snapshot dict from TradingEngine to runtime state."""
        account = snapshot.get("account", {})
        risk = snapshot.get("risk", {})
        margin = risk.get("margin", {})
        if isinstance(margin, dict):
            risk = {
                **risk,
                "margin_state": margin.get("action", "normal"),
                "margin_usage_pct": margin.get("margin_usage_pct", 0),
                "effective_leverage": margin.get("effective_leverage", 0),
                "concentration_pct": margin.get("concentration_pct", 0),
                "margin_level_pct": margin.get("margin_level_pct"),
                "net_directional_pct": margin.get("net_directional_pct", 0),
            }
            risk.pop("margin", None)

        now = datetime.now(timezone.utc)
        cycle_start = snapshot.get("last_cycle_at")
        next_cycle = snapshot.get("next_cycle_at")
        if cycle_start and not next_cycle:
            try:
                start_dt = datetime.fromisoformat(cycle_start.replace("Z", "+00:00"))
                next_cycle = (start_dt + timedelta(minutes=self.cycle_minutes)).isoformat()
            except ValueError:
                next_cycle = (now + timedelta(minutes=self.cycle_minutes)).isoformat()

        state = read_state(self.state_path)
        updates: dict[str, Any] = {
            "phase": snapshot.get("phase", state.get("phase")),
            "mode": snapshot.get("mode", state.get("mode")),
            "timestamp": snapshot.get("timestamp", now.isoformat()),
            "connected": snapshot.get("connected", False),
            "engine_running": snapshot.get("engine_running", state.get("engine_running", False)),
            "engine_paused": snapshot.get("engine_paused", state.get("engine_paused", False)),
            "cycle_in_progress": snapshot.get("cycle_in_progress", state.get("cycle_in_progress", False)),
            "mt5_connected": snapshot.get("mt5_connected", snapshot.get("connected", False)),
            "zmq_last_error": snapshot.get("zmq_last_error", state.get("zmq_last_error")),
            "account_profile": snapshot.get("account_profile", state.get("account_profile")),
            "account": {**state.get("account", {}), **account},
            "positions": snapshot.get("positions", []),
            "risk": {**state.get("risk", {}), **risk, "sharpe": risk.get("sharpe", 0)},
            "last_cycle": snapshot.get("last_cycle", state.get("last_cycle", {})),
        }
        if snapshot.get("engine_config"):
            updates["engine_config"] = snapshot["engine_config"]
        if cycle_start is not None:
            updates["last_cycle_at"] = cycle_start
        if next_cycle is not None:
            updates["next_cycle_at"] = next_cycle
        state.update(updates)
        phase = str(updates.get("phase") or state.get("phase") or "")
        state["phase_blocked_symbols"] = _phase_blocked_symbols(phase)
        last_cycle = updates.get("last_cycle") or state.get("last_cycle")
        if snapshot.get("instruments"):
            _merge_instruments(state, snapshot["instruments"], last_cycle=last_cycle)
        market = snapshot.get("market")
        if market is None:
            existing_market = state.get("market", {})
            market = {
                "last_tick_at": existing_market.get("last_tick_at"),
                "last_tick_age_ms": existing_market.get("last_tick_age_ms"),
            }
        state["market"] = market
        if snapshot.get("intelligence"):
            state["intelligence"] = snapshot["intelligence"]

        equity_raw = account.get("equity")
        equity: float | None = None
        if equity_raw is not None:
            try:
                parsed = float(equity_raw)
                if parsed > 0:
                    equity = parsed
            except (TypeError, ValueError):
                equity = None
        append_equity_point(state, equity, state["timestamp"])
        write_state(state, self.state_path)
        _notify_listeners(state)
        if equity is not None:
            logger.debug("Published runtime state — equity=%.2f", equity)
        else:
            logger.debug("Published runtime state — equity unavailable")
        return state

    def publish_cycle(
        self,
        *,
        phase: str,
        mode: str,
        connected: bool,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        risk: dict[str, Any],
        last_cycle: dict[str, Any],
        instruments: dict[str, Any] | None = None,
        sharpe: float = 0.0,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        state = read_state(self.state_path)
        state["phase"] = phase
        state["mode"] = mode
        state["timestamp"] = now.isoformat()
        state["last_cycle_at"] = now.isoformat()
        state["next_cycle_at"] = (now + timedelta(minutes=self.cycle_minutes)).isoformat()
        state["connected"] = connected
        state["engine_running"] = connected
        state["mt5_connected"] = connected and mode == "live"
        state["account"] = {
            **state.get("account", {}),
            **account,
        }
        state["positions"] = positions
        state["risk"] = {
            **state.get("risk", {}),
            **risk,
            "sharpe": sharpe,
        }
        state["last_cycle"] = last_cycle
        state["phase_blocked_symbols"] = _phase_blocked_symbols(phase)
        if instruments:
            _merge_instruments(state, instruments, last_cycle=last_cycle)

        equity_raw = account.get("equity")
        equity: float | None = None
        if equity_raw is not None:
            try:
                parsed = float(equity_raw)
                if parsed > 0:
                    equity = parsed
            except (TypeError, ValueError):
                equity = None
        append_equity_point(state, equity, now.isoformat())
        write_state(state, self.state_path)
        _notify_listeners(state)
        if equity is not None:
            logger.debug("Published runtime state — equity=%.2f tier=%s", equity, risk.get("dd_tier"))
        return state

    def publish_risk_event(
        self,
        event_type: str,
        message: str,
        severity: str = "warning",
        risk_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = read_state(self.state_path)
        append_risk_event(state, event_type, message, severity)
        if risk_patch:
            state["risk"] = {**state.get("risk", {}), **risk_patch}
        state["timestamp"] = datetime.now(timezone.utc).isoformat()
        write_state(state, self.state_path)
        _notify_listeners(state)
        logger.info("Risk event published: %s — %s", event_type, message)
        return state
