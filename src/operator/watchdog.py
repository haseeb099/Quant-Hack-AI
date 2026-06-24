"""Operator watchdog cycle — reconciliation, compliance, MT5 checks, snapshot persistence."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.operator.mt5_checks import run_mt5_checks
from src.operator.mt5_log_tail import tail_dwx_errors
from src.operator.reconciler import (
    count_jsonl_closed_since,
    count_jsonl_closed_without_votes,
    count_jsonl_partial_close_since,
    count_jsonl_unique_closed_tickets_since,
    reconcile_portfolio,
)
from src.engine.trade_journal import (
    count_mt5_closed_positions_since,
    count_mt5_partial_exit_deals_since,
)
from src.operator.risk_compliance import check_risk_compliance
from src.operator.alerts import dispatch_discipline_warning, dispatch_operator_alerts
from src.operator.snapshot_store import append_history, write_snapshot
from src.web.runtime_state import read_state


def _auth_headers() -> dict[str, str]:
    token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _fetch_json(client: httpx.Client, path: str) -> dict[str, Any] | list[Any] | None:
    try:
        response = client.get(path, headers=_auth_headers(), timeout=15.0)
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception:
        return None


def _count_mt5_deals_24h() -> tuple[int | None, int | None, int | None]:
    """Return (all_deals, exit_deals, closed_positions) for the last 24h."""
    try:
        import MetaTrader5 as mt5
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return None, None, None
        start = datetime.now(timezone.utc) - timedelta(hours=24)
        deals = mt5.history_deals_get(start, datetime.now(timezone.utc))
        if deals is None:
            return None, None, None
        exit_deals = sum(
            1 for d in deals if int(getattr(d, "entry", 0)) in (1, 2, 3)
        )
        closed_positions = count_mt5_closed_positions_since(hours=24)
        return len(deals), exit_deals, closed_positions
    except Exception:
        return None, None, None


def _memory_trade_count() -> int | None:
    try:
        from src.learning.layered_memory import LayeredMemory

        return LayeredMemory().trade_count()
    except Exception:
        return None


def _overall_status(*statuses: str) -> str:
    order = {"RED": 3, "YELLOW": 2, "GREEN": 1, "UNKNOWN": 0}
    best = "GREEN"
    for status in statuses:
        if order.get(status, 0) > order.get(best, 0):
            best = status
    return best


def run_operator_watchdog_cycle(
    *,
    dashboard_url: str | None = None,
    zmq_only: bool | None = None,
    equity_tolerance_pct: float | None = None,
    alert_notion: bool | None = None,
    persist: bool = True,
    dispatch_alerts: bool = True,
) -> dict[str, Any]:
    """Run one watchdog cycle and optionally persist snapshot + history."""
    dashboard_url = (dashboard_url or os.getenv("OPERATOR_DASHBOARD_URL", "http://127.0.0.1:8080")).rstrip("/")
    zmq_only = zmq_only if zmq_only is not None else os.getenv("OPERATOR_ZMQ_ONLY", "").lower() in ("1", "true", "yes")
    equity_tolerance_pct = equity_tolerance_pct or float(os.getenv("OPERATOR_EQUITY_TOLERANCE_PCT", "0.5"))
    notion_enabled = (
        alert_notion
        if alert_notion is not None
        else os.getenv("OPERATOR_ALERT_NOTION", "").lower() in ("1", "true", "yes")
    )

    state = read_state()
    mt5_positions: list[dict[str, Any]] | None = None
    mt5_account: dict[str, Any] | None = None
    open_trades: dict[int, dict[str, Any]] = {}
    engine_positions = state.get("positions", [])
    engine_account = state.get("account", {})

    with httpx.Client(base_url=dashboard_url) as client:
        positions_payload = _fetch_json(client, "/api/positions")
        if isinstance(positions_payload, dict):
            engine_positions = positions_payload.get("positions", engine_positions)
        account_payload = _fetch_json(client, "/api/account")
        if isinstance(account_payload, dict):
            engine_account = {**engine_account, **account_payload}
        open_payload = _fetch_json(client, "/api/engine/open_trades")
        if isinstance(open_payload, dict):
            raw_trades = open_payload.get("trades", {})
            if isinstance(raw_trades, dict):
                for ticket, trade in raw_trades.items():
                    try:
                        open_trades[int(ticket)] = trade
                    except (TypeError, ValueError):
                        continue
        calendar_payload = _fetch_json(client, "/api/intelligence/calendar")
        calendar_events: list[dict[str, Any]] = []
        if isinstance(calendar_payload, dict):
            calendar_events = calendar_payload.get("events", calendar_payload.get("items", []))

    try:
        from src.bridges.factory import create_live_connector

        conn = create_live_connector()
        try:
            if conn.connect():
                mt5_positions = conn.get_positions()
                mt5_account = conn.get_account_info()
        finally:
            conn.close()
    except Exception:
        pass

    deals_24h, exit_deals_24h, closed_positions_24h = _count_mt5_deals_24h()
    jsonl_closed = count_jsonl_closed_since()
    jsonl_unique_closed = count_jsonl_unique_closed_tickets_since()
    jsonl_votes_missing = count_jsonl_closed_without_votes()
    jsonl_partial = count_jsonl_partial_close_since()
    mt5_partial_exits = count_mt5_partial_exit_deals_since()
    memory_count = _memory_trade_count()

    reconciliation = reconcile_portfolio(
        mt5_positions=mt5_positions,
        engine_positions=engine_positions,
        mt5_account=mt5_account,
        engine_account=engine_account,
        open_trades=open_trades,
        equity_tolerance_pct=equity_tolerance_pct,
        deals_24h=deals_24h,
        jsonl_closed_24h=jsonl_closed,
        memory_trade_count=memory_count,
        closed_positions_24h=closed_positions_24h,
        exit_deals_24h=exit_deals_24h,
        jsonl_partial_close_24h=jsonl_partial,
        mt5_partial_exit_deals_24h=mt5_partial_exits,
        jsonl_unique_closed_tickets_24h=jsonl_unique_closed,
        jsonl_votes_missing_24h=jsonl_votes_missing,
    )
    risk = check_risk_compliance(state=state, calendar_events=calendar_events)
    mt5_checks = run_mt5_checks(zmq_only=zmq_only)
    mt5_log = tail_dwx_errors()

    mt5_check_status = "GREEN" if mt5_checks.get("ready") else "RED"
    overall = _overall_status(
        reconciliation["status"],
        risk["status"],
        mt5_check_status,
        mt5_log.get("status", "GREEN"),
    )

    snapshot: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "dashboard_url": dashboard_url,
        "reconciliation": reconciliation,
        "risk_compliance": risk,
        "mt5_checks": mt5_checks,
        "mt5_log": mt5_log,
        "summary": {
            **reconciliation.get("summary", {}),
            "jsonl_closed_24h": jsonl_closed,
            "jsonl_unique_closed_tickets_24h": jsonl_unique_closed,
            "deals_24h": deals_24h,
            "exit_deals_24h": exit_deals_24h,
            "closed_positions_24h": closed_positions_24h,
            "memory_trade_count": memory_count,
        },
    }

    if persist:
        write_snapshot(snapshot)
        append_history(snapshot)
        if dispatch_alerts:
            discipline = int((state.get("risk") or {}).get("discipline", 100))
            halt = (state.get("phase_rules") or {}).get("discipline_halt_below")
            if halt is not None:
                snapshot["discipline_warning"] = dispatch_discipline_warning(
                    discipline, halt_threshold=int(halt),
                )
            snapshot["alerts"] = dispatch_operator_alerts(snapshot, enable_notion=notion_enabled)

    return snapshot
