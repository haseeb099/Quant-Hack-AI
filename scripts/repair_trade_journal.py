#!/usr/bin/env python3
"""Repair trade journal gaps from MT5 closed deals (idempotent)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.bridges.factory import create_live_connector
from src.bridges.zeromq_connector import account_equity
from src.engine.config import QuantAIConfig
from src.engine.trade_journal import (
    backfill_closed_votes_in_jsonl,
    closed_tickets_from_jsonl,
    mt5_closed_tickets,
)
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def repair_journal(days: int = 7) -> dict:
    """Backfill missing closed tickets into logs/trades.jsonl via engine finalize logic."""
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load()
    engine = TradingEngine(config=config, simulation=False)
    engine.connector = create_live_connector()
    if not engine.connector.connect():
        return {"repaired": 0, "error": engine.connector.last_error or "Bridge connect failed"}

    account = engine.connector.get_account_info()
    equity = account_equity(account, simulation=False) or 1_000_000.0
    engine._initial_equity = equity
    engine._finalized_tickets = closed_tickets_from_jsonl(engine.trade_logger.jsonl_path)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    open_tickets = {
        int(p["ticket"])
        for p in engine.connector.get_positions()
        if p.get("ticket")
    }
    orphans = mt5_closed_tickets(
        since=since,
        open_tickets=open_tickets,
        finalized_tickets=engine._finalized_tickets,
    )

    repaired = 0
    for item in orphans:
        ticket = int(item["ticket"])
        if ticket in engine._open_trades:
            continue
        logger.info("Repairing journal for closed ticket %d (%s)", ticket, item.get("symbol", ""))
        pos = {
            "profit": item.get("profit", 0),
            "symbol": item.get("symbol", ""),
            "price_current": item.get("exit_price"),
        }
        before = len(engine._finalized_tickets)
        engine._finalize_trade(ticket, pos, equity)
        if len(engine._finalized_tickets) > before:
            repaired += 1

    engine.connector.close()
    return {"repaired": repaired, "candidates": len(orphans)}


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Repair trade journal from MT5 closed deals")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument(
        "--backfill-votes",
        action="store_true",
        help="Patch closed journal rows missing agent_votes from prior decision lines",
    )
    args = parser.parse_args()

    if args.backfill_votes:
        patched = backfill_closed_votes_in_jsonl(ROOT / "logs" / "trades.jsonl")
        logger.info("Backfilled agent_votes on %d closed journal rows", patched)

    result = repair_journal(days=args.days)
    if result.get("error"):
        logger.error("Repair failed: %s", result["error"])
        return 1
    logger.info(
        "Repair complete: %d/%d tickets finalized",
        result.get("repaired", 0),
        result.get("candidates", 0),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
