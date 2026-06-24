#!/usr/bin/env python3
"""CLI for historical agent replay backtest."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.learning.historical_backtest import HistoricalBacktester
from src.learning.layered_memory import LayeredMemory
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run historical agent replay backtest")
    parser.add_argument("--data-dir", default="data/historical", help="OHLCV data directory")
    parser.add_argument("--round-id", default="pricer_backtest", help="Round id for trade memory")
    parser.add_argument("--db", default="data/trade_memory.db", help="Trade memory database path")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    memory = LayeredMemory(db_path=args.db, round_id=args.round_id)
    backtester = HistoricalBacktester(memory=memory)
    results = backtester.run_directory(args.data_dir, round_id=args.round_id)

    total = sum(results.values())
    logger.info("Backtest complete: %d symbols, %d total trades", len(results), total)
    for sym, count in sorted(results.items()):
        if count:
            logger.info("  %s: %d trades", sym, count)


if __name__ == "__main__":
    main()
