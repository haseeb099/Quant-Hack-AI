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
    parser.add_argument(
        "--suggest-overrides",
        action="store_true",
        help="Write read-only weight deltas to data/phase_strategy_overrides.json",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    plan = run_adaptation(phase=args.phase, data_dir=args.data, output_path=args.output)
    logger.info("Adaptation complete (promoted=%s)", plan.get("promoted"))

    if args.suggest_overrides:
        import json

        overrides_path = Path("data/phase_strategy_overrides.json")
        suggestions = {
            "phase": args.phase,
            "source": "adapt_round.py — operator approval required before applying",
            "weight_deltas": plan.get("weight_deltas") or plan.get("agent_weight_deltas") or {},
            "promoted": plan.get("promoted"),
        }
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        overrides_path.write_text(json.dumps(suggestions, indent=2) + "\n", encoding="utf-8")
        logger.info("Wrote suggested overrides to %s", overrides_path)


if __name__ == "__main__":
    main()
