#!/usr/bin/env python3
"""Between-round adaptation — rebuild semantic layer, optimize weights, write plan."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.learning.adaptation_service import run_adaptation
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantAI round adaptation")
    parser.add_argument("--phase", default=os.getenv("QUANTAI_PHASE", "round1"))
    parser.add_argument("--data", default="data/historical", help="Historical data directory")
    parser.add_argument("--output", default="data/adaptation_plan.json")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    plan = run_adaptation(phase=args.phase, data_dir=args.data, output_path=args.output)
    logger.info("Adaptation complete (promoted=%s)", plan.get("promoted"))


if __name__ == "__main__":
    main()
