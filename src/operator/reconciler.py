"""Portfolio reconciliation — MT5 ground truth vs engine/dashboard state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

Severity = str  # INFO | WARNING | CRITICAL


def _issue(
    code: str,
    label: str,
    severity: Severity,
    passed: bool,
    detail: str = "",
    remediation: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "passed": passed,
        "detail": detail,
        "remediation": remediation,
    }


def _symbol_key(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def _volume_by_symbol(positions: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for pos in positions:
        symbol = str(pos.get("symbol", ""))
        if not symbol:
            continue
        key = _symbol_key(symbol)
        totals[key] = totals.get(key, 0.0) + float(pos.get("volume", 0) or 0)
    return totals


def count_jsonl_partial_close_since(
    path: Path | str = Path("logs/trades.jsonl"),
    hours: int = 24,
) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("status", "")).lower() != "partial_close":
                continue
            ts_raw = record.get("timestamp")
            if not ts_raw:
                count += 1
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except ValueError:
                count += 1
                continue
            if ts >= cutoff:
                count += 1
    return count


def count_jsonl_closed_since(
    path: Path | str = Path("logs/trades.jsonl"),
    hours: int = 24,
) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("status", "")).lower() != "closed":
                continue
            ts_raw = record.get("timestamp")
            if not ts_raw:
                count += 1
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except ValueError:
                count += 1
                continue
            if ts >= cutoff:
                count += 1
    return count


def count_jsonl_unique_closed_tickets_since(
    path: Path | str = Path("logs/trades.jsonl"),
    hours: int = 24,
) -> int:
    """Unique closed position tickets in jsonl within the window."""
    p = Path(path)
    if not p.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    tickets: set[int] = set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("status", "")).lower() != "closed":
                continue
            ts_raw = record.get("timestamp")
            in_window = True
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    in_window = ts >= cutoff
                except ValueError:
                    in_window = True
            if not in_window:
                continue
            ticket = record.get("ticket")
            if ticket is None:
                ticket = (record.get("extra") or {}).get("ticket")
            if ticket is not None:
                tickets.add(int(ticket))
    return len(tickets)


def count_jsonl_closed_without_votes(
    path: Path | str = Path("logs/trades.jsonl"),
    hours: int = 24,
) -> int:
    """Unique closed tickets in the window still missing agent_votes."""
    p = Path(path)
    if not p.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    tickets_missing: set[int] = set()
    tickets_with_votes: set[int] = set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("status", "")).lower() != "closed":
                continue
            ts_raw = record.get("timestamp")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            ticket = record.get("ticket")
            if ticket is None:
                ticket = (record.get("extra") or {}).get("ticket")
            if ticket is None:
                continue
            ticket_int = int(ticket)
            votes = record.get("agent_votes") or []
            if votes:
                tickets_with_votes.add(ticket_int)
            else:
                tickets_missing.add(ticket_int)
    return len(tickets_missing - tickets_with_votes)


def aggregate_status(issues: list[dict[str, Any]]) -> str:
    """Return GREEN, YELLOW, or RED from reconciliation issues."""
    failed = [i for i in issues if not i.get("passed", True)]
    if any(i.get("severity") == "CRITICAL" for i in failed):
        return "RED"
    if any(i.get("severity") == "WARNING" for i in failed):
        return "YELLOW"
    if failed:
        return "YELLOW"
    return "GREEN"


def reconcile_portfolio(
    *,
    mt5_positions: list[dict[str, Any]] | None,
    engine_positions: list[dict[str, Any]],
    mt5_account: dict[str, Any] | None,
    engine_account: dict[str, Any],
    open_trades: dict[int, dict[str, Any]] | None = None,
    equity_tolerance_pct: float = 0.5,
    deals_24h: int | None = None,
    jsonl_closed_24h: int | None = None,
    memory_trade_count: int | None = None,
    closed_positions_24h: int | None = None,
    closed_deals_count: int | None = None,
    exit_deals_24h: int | None = None,
    jsonl_partial_close_24h: int | None = None,
    mt5_partial_exit_deals_24h: int | None = None,
    jsonl_unique_closed_tickets_24h: int | None = None,
    jsonl_votes_missing_24h: int | None = None,
) -> dict[str, Any]:
    """Compare MT5 vs engine/dashboard and return structured reconciliation result."""
    issues: list[dict[str, Any]] = []
    open_trades = open_trades or {}

    mt5_positions = mt5_positions or []
    mt5_tickets = {int(p["ticket"]) for p in mt5_positions if p.get("ticket") is not None}
    engine_tickets = {int(p["ticket"]) for p in engine_positions if p.get("ticket") is not None}
    open_trade_tickets = {int(t) for t in open_trades.keys()}

    count_match = len(mt5_tickets) == len(engine_tickets) == len(mt5_positions) == len(engine_positions)
    if mt5_tickets != engine_tickets:
        count_match = False
    issues.append(
        _issue(
            "POSITION_COUNT",
            "Position ticket count",
            "CRITICAL",
            count_match and len(mt5_tickets) == len(engine_tickets),
            f"mt5={len(mt5_tickets)} engine={len(engine_tickets)}",
            "Reconcile MT5 vs dashboard positions; pause entries if mismatch persists",
        ),
    )

    unknown_mt5 = sorted(mt5_tickets - engine_tickets)
    issues.append(
        _issue(
            "UNKNOWN_MT5_POSITIONS",
            "Unknown MT5 positions",
            "CRITICAL",
            len(unknown_mt5) == 0,
            f"tickets={unknown_mt5}" if unknown_mt5 else "none",
            "Close or register external MT5 positions before resuming automation",
        ),
    )

    mt5_volumes = _volume_by_symbol(mt5_positions)
    engine_volumes = _volume_by_symbol(engine_positions)
    volume_mismatch: list[str] = []
    for key in sorted(set(mt5_volumes) | set(engine_volumes)):
        mt5_vol = mt5_volumes.get(key, 0.0)
        eng_vol = engine_volumes.get(key, 0.0)
        if abs(mt5_vol - eng_vol) > 1e-6:
            volume_mismatch.append(f"{key}: mt5={mt5_vol:.4f} engine={eng_vol:.4f}")
    issues.append(
        _issue(
            "SYMBOL_VOLUME",
            "Per-symbol volume",
            "WARNING",
            len(volume_mismatch) == 0,
            "; ".join(volume_mismatch) if volume_mismatch else "aligned",
            "Verify partial closes and bridge sync",
        ),
    )

    equity_delta_pct: float | None = None
    equity_ok = True
    if mt5_account and engine_account:
        mt5_equity = float(mt5_account.get("equity", 0) or 0)
        eng_equity = float(engine_account.get("equity", 0) or 0)
        if mt5_equity > 0 and eng_equity > 0:
            equity_delta_pct = abs(mt5_equity - eng_equity) / mt5_equity * 100
            equity_ok = equity_delta_pct <= equity_tolerance_pct
        detail = (
            f"mt5={mt5_equity:.2f} engine={eng_equity:.2f} delta={equity_delta_pct:.3f}%"
            if equity_delta_pct is not None
            else f"mt5={mt5_equity:.2f} engine={eng_equity:.2f}"
        )
    else:
        detail = "account data unavailable"
        equity_ok = mt5_account is not None or engine_account.get("equity") is not None
    issues.append(
        _issue(
            "EQUITY",
            "Equity alignment",
            "WARNING",
            equity_ok,
            detail,
            f"Tolerance {equity_tolerance_pct:.2f}% — refresh bridge or restart engine",
        ),
    )

    orphan_trades = sorted(open_trade_tickets - mt5_tickets)
    issues.append(
        _issue(
            "ORPHAN_OPEN_TRADES",
            "Engine open-trade ledger orphans",
            "WARNING",
            len(orphan_trades) == 0,
            f"tickets={orphan_trades}" if orphan_trades else "none",
            "Engine will finalize orphans on next cycle; verify trade_memory.db",
        ),
    )

    if closed_positions_24h is None and closed_deals_count is not None:
        closed_positions_24h = closed_deals_count

    if closed_positions_24h is not None and jsonl_unique_closed_tickets_24h is not None:
        delta = abs(closed_positions_24h - jsonl_unique_closed_tickets_24h)
        baseline = max(closed_positions_24h, jsonl_unique_closed_tickets_24h, 1)
        tolerance = max(3, int(baseline * 0.35))
        if jsonl_partial_close_24h:
            tolerance += int(jsonl_partial_close_24h)
        positions_ok = delta <= tolerance
        issues.append(
            _issue(
                "CLOSED_POSITIONS_JSONL",
                "MT5 closed positions vs jsonl unique closes (24h)",
                "WARNING",
                positions_ok,
                (
                    f"closed_positions={closed_positions_24h} "
                    f"jsonl_unique_closed={jsonl_unique_closed_tickets_24h}"
                ),
                "Check trade lifecycle finalize paths and logs/trades.jsonl",
            ),
        )
    elif closed_positions_24h is not None and jsonl_closed_24h is not None:
        delta = abs(closed_positions_24h - jsonl_closed_24h)
        tolerance = max(2, int(closed_positions_24h * 0.10))
        positions_ok = delta <= tolerance
        issues.append(
            _issue(
                "CLOSED_POSITIONS_JSONL",
                "MT5 closed positions vs jsonl closes (24h)",
                "WARNING",
                positions_ok,
                f"closed_positions={closed_positions_24h} jsonl_closed={jsonl_closed_24h}",
                "Check trade lifecycle finalize paths and logs/trades.jsonl",
            ),
        )
    elif deals_24h is not None and jsonl_closed_24h is not None and closed_positions_24h is None:
        delta = abs(deals_24h - jsonl_closed_24h)
        deals_ok = delta <= max(2, int(deals_24h * 0.10))
        issues.append(
            _issue(
                "DEALS_JSONL",
                "MT5 deals vs jsonl closes (24h)",
                "WARNING",
                deals_ok,
                f"deals={deals_24h} jsonl_closed={jsonl_closed_24h}",
                "Check trade lifecycle finalize paths and logs/trades.jsonl",
            ),
        )

    memory_baseline = jsonl_unique_closed_tickets_24h
    if memory_baseline is None:
        memory_baseline = closed_positions_24h
    if memory_baseline is not None and memory_trade_count is not None:
        backlog = max(0, memory_baseline - memory_trade_count)
        issues.append(
            _issue(
                "MEMORY_BACKFILL",
                "Closed trades vs trade memory",
                "INFO",
                backlog <= max(2, int(memory_baseline * 0.10)),
                f"baseline={memory_baseline} memory={memory_trade_count} backlog≈{backlog}",
                "Run backfill_trade_memory when Phase 2 is available",
            ),
        )

    if jsonl_partial_close_24h is not None or mt5_partial_exit_deals_24h is not None:
        jsonl_partials = jsonl_partial_close_24h or 0
        mt5_partials = mt5_partial_exit_deals_24h or 0
        issues.append(
            _issue(
                "PARTIAL_CLOSE_AUDIT",
                "Partial close journal vs MT5 exit deals (24h)",
                "INFO",
                True,
                f"jsonl_partial_close={jsonl_partials} mt5_partial_exits={mt5_partials}",
                "Informational — partial closes inflate exit-deal counts",
            ),
        )

    if jsonl_votes_missing_24h is not None and jsonl_votes_missing_24h > 0:
        votes_ok = jsonl_votes_missing_24h <= max(3, int(jsonl_unique_closed_tickets_24h or 0) * 0.15)
        issues.append(
            _issue(
                "VOTES_MISSING",
                "Closed trades missing agent votes (24h)",
                "WARNING",
                votes_ok,
                f"missing_votes={jsonl_votes_missing_24h}",
                "Run scripts/repair_trade_journal.py --backfill-votes",
            ),
        )

    status = aggregate_status(issues)
    return {
        "status": status,
        "issues": issues,
        "summary": {
            "mt5_position_count": len(mt5_tickets),
            "engine_position_count": len(engine_tickets),
            "open_trades_count": len(open_trades),
            "orphan_trades": orphan_trades,
            "unknown_mt5_tickets": unknown_mt5,
            "equity_delta_pct": equity_delta_pct,
            "closed_positions_24h": closed_positions_24h,
            "exit_deals_24h": exit_deals_24h,
        },
    }
