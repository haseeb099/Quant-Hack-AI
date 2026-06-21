#!/usr/bin/env python3
"""Between-round adaptation — rebuild semantic layer, optimize weights, write plan."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory
from src.learning.walk_forward import WalkForwardValidator
from src.learning.weight_optimizer import WeightOptimizer
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

    config = QuantAIConfig.load(phase=args.phase)
    memory = LayeredMemory(round_id=args.phase)
    memory.rebuild_semantic_layer()

    base_weights = {
        name: cfg.get("weight", 0.25)
        for name, cfg in config.agents.items()
        if name != "meta_orchestrator"
    }

    optimizer = WeightOptimizer(base_weights, memory)
    new_weights = optimizer.optimize()

    wf = WalkForwardValidator()
    data_path = Path(args.data)
    historical_files = list(data_path.glob("*.parquet")) + list(data_path.glob("*.csv"))
    wf_result = None
    if historical_files:
        wf_result = wf.validate(
            run_id=f"adapt_{args.phase}",
            params=new_weights,
            historical_data_path=str(historical_files[0]),
            baseline_weights=base_weights,
        )

    promoted = wf_result.promoted if wf_result else False
    if wf_result and not optimizer.should_promote(
        base_weights,
        new_weights,
        wf_result.oos_sharpe - wf_result.baseline_sharpe,
    ):
        new_weights = base_weights
        promoted = False

    plan = {
        "phase": args.phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "old_weights": base_weights,
        "new_weights": new_weights,
        "promoted": promoted,
        "walk_forward": {
            "oos_return": wf_result.oos_return if wf_result else 0,
            "oos_sharpe": wf_result.oos_sharpe if wf_result else 0,
            "oos_max_dd": wf_result.oos_max_dd if wf_result else 0,
        },
        "semantic_keys": len(memory._semantic),
        "trade_count": memory.agent_performance("trend_surfer")["sample_size"],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    logger.info("Adaptation plan written to %s (promoted=%s)", output_path, promoted)


if __name__ == "__main__":
    main()
