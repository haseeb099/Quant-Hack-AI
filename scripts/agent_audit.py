#!/usr/bin/env python3
"""Generate agent audit report from trade memory."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from src.learning.agent_audit import run_agent_audit
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run agent audit report")
    parser.add_argument("--output", default="data/agent_audit.json")
    parser.add_argument("--round-id", action="append", dest="round_ids")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()
    report = run_agent_audit(output_path=args.output, round_ids=args.round_ids)
    logger.info("Audit complete: %d trades, %d recommendations",
                report["trade_count"], len(report.get("recommendations", [])))


if __name__ == "__main__":
    main()
