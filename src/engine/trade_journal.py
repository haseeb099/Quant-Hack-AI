"""Helpers to recover trade context and backfill closed-trade journal gaps."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_OUT_BY = 3
_EXIT_ENTRIES = (DEAL_ENTRY_OUT, 2, DEAL_ENTRY_OUT_BY)

_STATUS_PRIORITY = {
    "ok": 5,
    "simulated": 5,
    "executed": 4,
    "decision": 3,
    "closed": 2,
}


def _group_deals_by_position(deals: list[Any]) -> dict[int, list[Any]]:
    by_position: dict[int, list[Any]] = {}
    for deal in deals:
        pos_id = int(getattr(deal, "position_id", 0) or 0)
        if pos_id <= 0:
            continue
        by_position.setdefault(pos_id, []).append(deal)
    return by_position


def count_mt5_closed_positions_since(hours: int = 24) -> int | None:
    """Count fully closed MT5 positions whose last exit deal falls within the window."""
    try:
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return None
        import MetaTrader5 as mt5

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        deals = mt5.history_deals_get(cutoff - timedelta(days=30), now)
        if deals is None:
            return None

        open_tickets = {
            int(getattr(p, "ticket", 0) or 0)
            for p in (mt5.positions_get() or [])
        }
        closed = 0
        for pos_id, group in _group_deals_by_position(list(deals)).items():
            entries = [d for d in group if int(getattr(d, "entry", -1)) == DEAL_ENTRY_IN]
            exits = [d for d in group if int(getattr(d, "entry", -1)) in _EXIT_ENTRIES]
            if not entries or not exits:
                continue
            last_exit = max(exits, key=lambda d: int(getattr(d, "time", 0) or 0))
            exit_ts = int(getattr(last_exit, "time", 0) or 0)
            if exit_ts < int(cutoff.timestamp()):
                continue
            if pos_id in open_tickets:
                continue
            closed += 1
        return closed
    except Exception:
        logger.debug("MT5 closed-position count failed", exc_info=True)
        return None


def count_mt5_exit_deals_since(hours: int = 24) -> int | None:
    """Count exit deals in the window (diagnostics — inflates vs closed positions)."""
    try:
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return None
        import MetaTrader5 as mt5

        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        deals = mt5.history_deals_get(start, datetime.now(timezone.utc))
        if deals is None:
            return None
        return sum(
            1 for d in deals if int(getattr(d, "entry", 0)) in _EXIT_ENTRIES
        )
    except Exception:
        logger.debug("MT5 exit-deal count failed", exc_info=True)
        return None


def count_mt5_partial_exit_deals_since(hours: int = 24) -> int | None:
    """Count exit deals on positions that remain open or had multiple exits (partial closes)."""
    try:
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return None
        import MetaTrader5 as mt5

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        deals = mt5.history_deals_get(cutoff - timedelta(days=7), now)
        if deals is None:
            return None

        open_tickets = {
            int(getattr(p, "ticket", 0) or 0)
            for p in (mt5.positions_get() or [])
        }
        partial = 0
        for pos_id, group in _group_deals_by_position(list(deals)).items():
            exits = [
                d for d in group
                if int(getattr(d, "entry", -1)) in _EXIT_ENTRIES
                and int(getattr(d, "time", 0) or 0) >= int(cutoff.timestamp())
            ]
            if not exits:
                continue
            if len(exits) > 1 or pos_id in open_tickets:
                partial += len(exits)
        return partial
    except Exception:
        logger.debug("MT5 partial-exit count failed", exc_info=True)
        return None


def closed_tickets_from_jsonl(path: Path | str) -> set[int]:
    """Tickets already written to the journal with status=closed."""
    closed: set[int] = set()
    journal = Path(path)
    if not journal.exists():
        return closed
    with open(journal, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") != "closed":
                continue
            ticket = rec.get("ticket")
            if ticket is None:
                ticket = (rec.get("extra") or {}).get("ticket")
            if ticket is not None:
                closed.add(int(ticket))
    return closed


def count_jsonl_closed_missing_votes_since(
    path: Path | str = Path("logs/trades.jsonl"),
    hours: int = 24,
) -> int:
    """Unique closed tickets in the window still missing agent_votes."""
    journal = Path(path)
    if not journal.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    tickets_missing: set[int] = set()
    tickets_with_votes: set[int] = set()
    with open(journal, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("status", "")).lower() != "closed":
                continue
            ts_raw = rec.get("timestamp")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            ticket = rec.get("ticket")
            if ticket is None:
                ticket = (rec.get("extra") or {}).get("ticket")
            if ticket is None:
                continue
            ticket_int = int(ticket)
            votes = rec.get("agent_votes") or []
            if votes:
                tickets_with_votes.add(ticket_int)
            else:
                tickets_missing.add(ticket_int)
    return len(tickets_missing - tickets_with_votes)


def context_from_jsonl(ticket: int, path: Path | str) -> dict[str, Any]:
    """Best-effort open-trade context — merges richest agent_votes across all journal lines."""
    journal = Path(path)
    if not journal.exists():
        return {}

    ticket_str = str(ticket)
    best: dict[str, Any] = {}
    best_priority = -1
    merged_votes: list[Any] = []

    with open(journal, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or ticket_str not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec_ticket = rec.get("ticket")
            if rec_ticket is None:
                rec_ticket = (rec.get("extra") or {}).get("ticket")
            if str(rec_ticket) != ticket_str:
                continue
            if rec.get("status") not in ("ok", "simulated", "executed", "decision", "closed"):
                continue

            votes = rec.get("agent_votes") or []
            if isinstance(votes, list) and len(votes) > len(merged_votes):
                merged_votes = votes

            priority = _STATUS_PRIORITY.get(str(rec.get("status", "")), 0)
            if priority >= best_priority:
                best_priority = priority
                best = rec

    if not best:
        return {}

    entry_price = float((best.get("extra") or {}).get("entry_price") or 0)
    if entry_price <= 0 and best.get("status") in ("ok", "simulated"):
        slip = best.get("slippage")
        if isinstance(slip, (int, float)) and float(slip) > 0:
            slip_val = float(slip)
            symbol = str(best.get("symbol", ""))
            if "JPY" in symbol.replace("/", "").upper():
                if slip_val >= 10:
                    entry_price = slip_val
            elif slip_val >= 0.5:
                entry_price = slip_val

    votes = merged_votes if merged_votes else (best.get("agent_votes") or [])
    agent = "recovered"
    if votes and isinstance(votes[0], dict):
        agent = str(votes[0].get("agent", agent)).replace("Direction.", "")

    extra = best.get("extra") or {}
    return {
        "symbol": best.get("symbol", ""),
        "direction": str(best.get("direction", "")).replace("Direction.", ""),
        "entry_price": entry_price,
        "sl": best.get("sl"),
        "session": best.get("session", "unknown"),
        "regime": best.get("regime", "unknown"),
        "agent": agent,
        "agent_votes": votes if isinstance(votes, list) else [],
        "reasoning": best.get("reasoning", "Recovered from trade journal"),
        "entry_time": best.get("timestamp", ""),
        "features_snapshot": extra.get("features_snapshot", {}),
        "attribution_json": extra.get("attribution_json", {}),
        "volume": float(best.get("size", 0) or extra.get("volume", 0) or 0),
    }


def backfill_closed_votes_in_jsonl(path: Path | str = Path("logs/trades.jsonl")) -> int:
    """Patch closed journal rows missing agent_votes from richer prior lines for the same ticket."""
    journal = Path(path)
    if not journal.exists():
        return 0

    lines: list[str] = []
    updated = 0
    with open(journal, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                lines.append(stripped)
                continue
            if str(rec.get("status", "")).lower() != "closed":
                lines.append(stripped)
                continue
            votes = rec.get("agent_votes") or []
            if votes:
                lines.append(stripped)
                continue
            ticket = rec.get("ticket")
            if ticket is None:
                ticket = (rec.get("extra") or {}).get("ticket")
            if ticket is None:
                lines.append(stripped)
                continue
            ctx = context_from_jsonl(int(ticket), journal)
            merged = ctx.get("agent_votes") or []
            if not merged:
                lines.append(stripped)
                continue
            rec["agent_votes"] = merged
            if not rec.get("reasoning") and ctx.get("reasoning"):
                rec["reasoning"] = ctx.get("reasoning")
            lines.append(json.dumps(rec, default=str))
            updated += 1

    if updated:
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated


def display_symbol(mt5_symbol: str) -> str:
    from src.bridges.zeromq_connector import ZeroMQConnector

    return ZeroMQConnector._display_symbol(mt5_symbol)


def build_tracked_from_mt5_deals(
    ticket: int,
    *,
    jsonl_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build ledger context for finalize when _open_trades missed the entry."""
    try:
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return None
        import MetaTrader5 as mt5

        deals = mt5.history_deals_get(position=ticket)
        if not deals:
            return None

        deals = sorted(deals, key=lambda d: int(getattr(d, "time", 0) or 0))
        entries = [d for d in deals if int(getattr(d, "entry", -1)) == DEAL_ENTRY_IN]
        if not entries:
            return None
        entry = entries[0]
        direction = "BUY" if int(getattr(entry, "type", 0)) == 0 else "SELL"
        symbol = display_symbol(str(getattr(entry, "symbol", "")))
        ctx = jsonl_context or {}
        entry_price = float(getattr(entry, "price", 0) or 0)
        if entry_price <= 0:
            entry_price = float(ctx.get("entry_price", 0) or 0)

        return {
            "symbol": ctx.get("symbol") or symbol,
            "direction": ctx.get("direction") or direction,
            "entry_price": entry_price,
            "sl": ctx.get("sl"),
            "session": ctx.get("session", "unknown"),
            "regime": ctx.get("regime", "unknown"),
            "agent": ctx.get("agent", "recovered"),
            "features_snapshot": ctx.get("features_snapshot", {}),
            "agent_votes": ctx.get("agent_votes", []),
            "attribution_json": ctx.get("attribution_json", {}),
            "reasoning": ctx.get("reasoning", "Recovered from MT5 deal history"),
            "entry_time": ctx.get("entry_time")
            or datetime.fromtimestamp(int(getattr(entry, "time", 0)), tz=timezone.utc).isoformat(),
            "volume": float(ctx.get("volume", 0) or getattr(entry, "volume", 0) or 0),
        }
    except Exception:
        logger.debug("Failed to build tracked context for ticket %d", ticket, exc_info=True)
        return None


def mt5_closed_tickets(
    *,
    since: datetime,
    open_tickets: set[int],
    finalized_tickets: set[int],
) -> list[dict[str, Any]]:
    """Closed MT5 positions not open and not yet finalized in our journal."""
    try:
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if not ok:
            return []
        import MetaTrader5 as mt5

        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if not deals:
            return []

        by_position: dict[int, list[Any]] = {}
        for deal in deals:
            pos_id = int(getattr(deal, "position_id", 0) or 0)
            if pos_id <= 0:
                continue
            by_position.setdefault(pos_id, []).append(deal)

        closed: list[dict[str, Any]] = []
        for pos_id, group in by_position.items():
            if pos_id in open_tickets or pos_id in finalized_tickets:
                continue
            group = sorted(group, key=lambda d: int(getattr(d, "time", 0) or 0))
            has_entry = any(int(getattr(d, "entry", -1)) == DEAL_ENTRY_IN for d in group)
            has_exit = any(int(getattr(d, "entry", -1)) == DEAL_ENTRY_OUT for d in group)
            if not has_entry or not has_exit:
                continue
            profit = float(sum(float(getattr(d, "profit", 0) or 0) for d in group))
            exit_deals = [d for d in group if int(getattr(d, "entry", -1)) == DEAL_ENTRY_OUT]
            exit_deal = exit_deals[-1]
            closed.append({
                "ticket": pos_id,
                "symbol": display_symbol(str(getattr(exit_deals[0], "symbol", ""))),
                "profit": profit,
                "exit_price": float(getattr(exit_deal, "price", 0) or 0),
            })
        return closed
    except Exception:
        logger.debug("MT5 closed ticket scan failed", exc_info=True)
        return []
