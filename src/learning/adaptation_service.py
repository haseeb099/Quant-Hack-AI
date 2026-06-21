"""Between-round adaptation — shared logic for CLI and dashboard API."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory
from src.learning.walk_forward import WalkForwardValidator
from src.learning.weight_optimizer import WeightOptimizer

logger = logging.getLogger(__name__)

DEFAULT_PLAN_PATH = Path("data/adaptation_plan.json")


def run_adaptation(
    phase: str | None = None,
    data_dir: str | Path = "data/historical",
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Rebuild semantic memory, optimize weights, walk-forward validate, write plan."""
    phase = phase or os.getenv("QUANTAI_PHASE", "round1")
    output_path = Path(output_path or DEFAULT_PLAN_PATH)
    data_path = Path(data_dir)

    config = QuantAIConfig.load(phase=phase)
    memory = LayeredMemory(round_id=phase)
    memory.rebuild_semantic_layer()

    base_weights = {
        name: float(cfg.get("weight", 0.25))
        for name, cfg in config.agents.items()
        if name != "meta_orchestrator"
    }

    optimizer = WeightOptimizer(base_weights, memory)
    new_weights = optimizer.optimize()

    wf = WalkForwardValidator()
    historical_files = list(data_path.glob("*.parquet")) + list(data_path.glob("*.csv"))
    wf_result = None
    if historical_files:
        wf_result = wf.validate(
            run_id=f"adapt_{phase}",
            params=new_weights,
            historical_data_path=str(historical_files[0]),
            baseline_weights=base_weights,
        )

    promoted = wf_result.promoted if wf_result else False
    sharpe_delta = (wf_result.oos_sharpe - wf_result.baseline_sharpe) if wf_result else 0.0
    if wf_result and not optimizer.should_promote(base_weights, new_weights, sharpe_delta):
        new_weights = base_weights
        promoted = False

    weight_deltas = {
        agent: round(new_weights.get(agent, 0) - base_weights.get(agent, 0), 4)
        for agent in base_weights
    }

    plan: dict[str, Any] = {
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "old_weights": base_weights,
        "new_weights": new_weights,
        "weight_deltas": weight_deltas,
        "promoted": promoted,
        "walk_forward": {
            "oos_return": wf_result.oos_return if wf_result else 0.0,
            "oos_sharpe": wf_result.oos_sharpe if wf_result else 0.0,
            "oos_max_dd": wf_result.oos_max_dd if wf_result else 0.0,
            "baseline_sharpe": wf_result.baseline_sharpe if wf_result else 0.0,
            "sharpe_delta": sharpe_delta,
            "historical_file": str(historical_files[0]) if historical_files else None,
        },
        "semantic_keys": memory.semantic_key_count(),
        "trade_count": memory.trade_count(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    logger.info("Adaptation plan written to %s (promoted=%s)", output_path, promoted)
    return plan


def load_adaptation_plan(path: Path | str | None = None) -> dict[str, Any] | None:
    p = Path(path or DEFAULT_PLAN_PATH)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read adaptation plan: %s", exc)
        return None
