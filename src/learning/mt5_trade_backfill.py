"""Backfill trade_memory.db from MT5 deal history + engine jsonl."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.learning.layered_memory import LayeredMemory, TradeRecord, build_trade_attribution
from src.engine.trade_journal import display_symbol

logger = logging.getLogger(__name__)


def _load_jsonl_decisions(path: Path) -> dict[str, Any]:
    """Index decision records by ticket and symbol for vote enrichment."""
    by_ticket: dict[str, dict[str, Any]] = {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return {"by_ticket": by_ticket, "by_symbol": by_symbol}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") not in ("executed", "ok", "simulated", "decision", "closed"):
                continue
            extra = rec.get("extra") or {}
            ticket = extra.get("ticket") or rec.get("ticket")
            symbol = rec.get("symbol", "")
            if ticket:
                existing = by_ticket.get(str(ticket))
                existing_votes = (existing or {}).get("agent_votes") or []
                new_votes = rec.get("agent_votes") or []
                if existing is None or len(new_votes) > len(existing_votes):
                    by_ticket[str(ticket)] = rec
            if symbol:
                by_symbol.setdefault(symbol, []).append(rec)
    for symbol, recs in by_symbol.items():
        recs.sort(key=lambda r: str(r.get("timestamp", "")))
    return {"by_ticket": by_ticket, "by_symbol": by_symbol}


def _nearest_jsonl_by_symbol(
    symbol: str,
    entry_time: str,
    by_symbol: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candidates = by_symbol.get(symbol, [])
    if not candidates:
        return {}
    try:
        target = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
    except ValueError:
        return candidates[-1]

    best: dict[str, Any] = {}
    best_delta = float("inf")
    for rec in candidates:
        ts_raw = rec.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = abs((ts - target).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best = rec
    return best or candidates[-1]


def _pair_deals(deals: list[Any]) -> list[dict[str, Any]]:
    """Pair entry/exit deals by position_id."""
    by_position: dict[int, list[Any]] = {}
    for deal in deals:
        pos_id = int(getattr(deal, "position_id", 0) or 0)
        if pos_id <= 0:
            continue
        by_position.setdefault(pos_id, []).append(deal)

    paired: list[dict[str, Any]] = []
    for pos_id, group in by_position.items():
        group = sorted(group, key=lambda d: int(getattr(d, "time", 0) or 0))
        entries = [d for d in group if int(getattr(d, "entry", 0)) == 0]
        exits = [d for d in group if int(getattr(d, "entry", 0)) == 1]
        if not entries or not exits:
            continue
        entry = entries[0]
        exit_deal = exits[-1]
        direction = "BUY" if int(getattr(entry, "type", 0)) == 0 else "SELL"
        entry_price = float(getattr(entry, "price", 0))
        exit_price = float(getattr(exit_deal, "price", 0))
        pnl = float(sum(getattr(d, "profit", 0) for d in group))
        ticket = int(getattr(entry, "position_id", pos_id))
        paired.append({
            "trade_id": str(ticket),
            "ticket": ticket,
            "symbol": display_symbol(str(getattr(entry, "symbol", ""))),
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "entry_time": datetime.fromtimestamp(
                int(getattr(entry, "time", 0)), tz=timezone.utc,
            ).isoformat(),
            "exit_time": datetime.fromtimestamp(
                int(getattr(exit_deal, "time", 0)), tz=timezone.utc,
            ).isoformat(),
        })
    return paired


def _normalize_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if len(symbol) == 6:
        return f"{symbol[:3]}/{symbol[3:]}"
    return symbol


def _build_record(
    trade: dict[str, Any],
    jsonl_rec: dict[str, Any],
    round_id: str,
) -> TradeRecord:
    symbol = _normalize_symbol(display_symbol(trade["symbol"]))
    agent_votes = jsonl_rec.get("agent_votes") or []
    primary = "unknown"
    if agent_votes:
        primary = str(agent_votes[0].get("agent", "unknown"))
    attribution = build_trade_attribution(
        signals=agent_votes,
        decision_direction=trade["direction"],
        primary_agent=primary,
        orchestrator_used_ai=False,
    )
    sl_dist = abs(trade["entry_price"] - trade["exit_price"]) * 0.5 or trade["entry_price"] * 0.001
    if trade["direction"] == "BUY":
        move = trade["exit_price"] - trade["entry_price"]
    else:
        move = trade["entry_price"] - trade["exit_price"]
    r_multiple = move / max(sl_dist, 1e-9)

    return TradeRecord(
        trade_id=trade["trade_id"],
        symbol=symbol,
        session="backfill",
        regime=jsonl_rec.get("regime", "unknown"),
        agent=primary,
        direction=trade["direction"],
        entry_price=trade["entry_price"],
        exit_price=trade["exit_price"],
        r_multiple=r_multiple,
        pnl=trade["pnl"],
        agent_votes=agent_votes if isinstance(agent_votes, list) else [],
        attribution_json=attribution,
        orchestrator_reasoning=jsonl_rec.get("reasoning", "mt5 backfill"),
        entry_time=trade["entry_time"],
        exit_time=trade["exit_time"],
        round_id=round_id,
    )


def backfill_from_mt5(
    *,
    memory: LayeredMemory | None = None,
    jsonl_path: str | Path = "logs/trades.jsonl",
    round_id: str = "mt5_backfill",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Pull MT5 deals and upsert into trade memory."""
    memory = memory or LayeredMemory(round_id=round_id)
    jsonl_index = _load_jsonl_decisions(Path(jsonl_path))

    try:
        import MetaTrader5 as mt5
        from src.integrations.mt5_session import ensure_mt5_session

        ok, detail = ensure_mt5_session()
        if not ok:
            return {"inserted": 0, "updated": 0, "skipped": 0, "error": detail}
    except ImportError:
        return {"inserted": 0, "updated": 0, "skipped": 0, "error": "MetaTrader5 not installed"}

    date_from = date_from or datetime(2020, 1, 1, tzinfo=timezone.utc)
    date_to = date_to or datetime.now(timezone.utc)
    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        return {"inserted": 0, "updated": 0, "skipped": 0, "error": str(mt5.last_error())}

    paired = _pair_deals(list(deals))
    inserted = 0
    updated = 0
    skipped = 0

    with sqlite3.connect(memory.db_path) as conn:
        existing_rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT trade_id, agent_votes FROM trades",
            ).fetchall()
        }

    for trade in paired:
        trade_id = trade["trade_id"]
        symbol = _normalize_symbol(display_symbol(trade["symbol"]))
        jsonl_rec = jsonl_index["by_ticket"].get(trade_id, {})
        if not jsonl_rec.get("agent_votes"):
            fallback = _nearest_jsonl_by_symbol(
                symbol, trade["entry_time"], jsonl_index["by_symbol"],
            )
            if fallback.get("agent_votes"):
                jsonl_rec = fallback

        record = _build_record(trade, jsonl_rec, round_id)

        if trade_id in existing_rows:
            stored_votes = existing_rows[trade_id]
            has_votes = bool(stored_votes and stored_votes not in ("[]", ""))
            if has_votes and not record.agent_votes:
                skipped += 1
                continue
            if record.agent_votes or not has_votes:
                memory.store_trade(record)
                updated += 1
            else:
                skipped += 1
            continue

        memory.store_trade(record)
        inserted += 1

    memory.rebuild_semantic_layer()
    logger.info("MT5 backfill: inserted=%d updated=%d skipped=%d", inserted, updated, skipped)
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "paired": len(paired)}
