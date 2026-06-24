#!/usr/bin/env python3
"""Backfill trade_memory.db from MT5 deal history."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from src.learning.mt5_trade_backfill import backfill_from_mt5
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill trade memory from MT5 deals")
    parser.add_argument("--jsonl", default="logs/trades.jsonl")
    parser.add_argument("--round-id", default="mt5_backfill")
    parser.add_argument("--days", type=int, default=30, help="Lookback days for deals")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()
    date_to = datetime.now(timezone.utc)
    date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
    if args.days > 0:
        from datetime import timedelta
        date_from = date_to - timedelta(days=args.days)

    result = backfill_from_mt5(
        jsonl_path=args.jsonl,
        round_id=args.round_id,
        date_from=date_from,
        date_to=date_to,
    )
    logger.info("Backfill result: %s", result)
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
