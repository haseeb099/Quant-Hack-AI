"""Between-round adaptation — shared logic for CLI and dashboard API."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.engine.config import QuantAIConfig
from src.learning.agent_audit import run_agent_audit
from src.learning.layered_memory import LayeredMemory
from src.learning.parameter_optimizer import ParameterOptimizer
from src.learning.regime_boost_optimizer import RegimeBoostOptimizer
from src.learning.walk_forward import WalkForwardValidator
from src.learning.weight_optimizer import WeightOptimizer
from src.operator.agent_health import load_agent_health, run_agent_health

logger = logging.getLogger(__name__)

DEFAULT_PLAN_PATH = Path("data/adaptation_plan.json")
TUNED_YAML_PATH = Path("data/agents_tuned.yaml")


def _promotion_gate(
    wf_result: Any,
    sharpe_delta: float,
    agent_health_status: str,
) -> tuple[bool, str | None]:
    if wf_result is None:
        return False, "no walk-forward result"
    if sharpe_delta <= 0.02:
        return False, "oos_sharpe_delta below threshold"
    if wf_result.oos_return <= 0:
        return False, "oos_return not positive"
    if wf_result.oos_max_dd >= 0.12:
        return False, "oos_max_dd above 12%"
    if agent_health_status == "RED":
        return False, "agent_health RED"
    return True, None


def run_adaptation(
    phase: str | None = None,
    data_dir: str | Path = "data/historical",
    output_path: str | Path | None = None,
    skip_health: bool = False,
) -> dict[str, Any]:
    """Rebuild semantic memory, optimize weights/params/boosts, walk-forward validate, write plan."""
    phase = phase or os.getenv("QUANTAI_PHASE", "round1")
    output_path = Path(output_path or DEFAULT_PLAN_PATH)
    data_path = Path(data_dir)

    config = QuantAIConfig.load(phase=phase)
    memory = LayeredMemory(round_id=phase)
    memory.rebuild_semantic_layer()

    health = load_agent_health()
    if not health and not skip_health:
        health = run_agent_health(persist=True)
    agent_health_status = (health or {}).get("status", "YELLOW")

    audit = run_agent_audit(persist=True)

    base_weights = {
        name: float(cfg.get("weight", 0.25))
        for name, cfg in config.agents.items()
        if name != "meta_orchestrator"
    }

    weight_opt = WeightOptimizer(base_weights, memory)
    new_weights = weight_opt.optimize()

    param_opt = ParameterOptimizer(config, memory)
    tuned_agents, parameter_deltas = param_opt.optimize()

    boost_opt = RegimeBoostOptimizer(config, memory)
    new_boosts, regime_boost_deltas = boost_opt.optimize()

    param_opt.write_tuned_yaml(tuned_agents, regime_boosts=new_boosts)

    wf = WalkForwardValidator()
    historical_files = list(data_path.glob("*.parquet")) + list(data_path.glob("*.csv"))
    wf_result = None
    if historical_files:
        wf_result = wf.validate_all_symbols(
            run_id=f"adapt_{phase}",
            params=new_weights,
            data_dir=data_path,
            baseline_weights=base_weights,
        )

    sharpe_delta = (wf_result.oos_sharpe - wf_result.baseline_sharpe) if wf_result else 0.0
    promoted, blocked_reason = _promotion_gate(wf_result, sharpe_delta, agent_health_status)

    if wf_result and not weight_opt.should_promote(base_weights, new_weights, sharpe_delta):
        new_weights = base_weights
        promoted = False
        blocked_reason = blocked_reason or "weight optimizer rejected promotion"

    if not promoted:
        new_weights = base_weights

    weight_deltas = {
        agent: round(new_weights.get(agent, 0) - base_weights.get(agent, 0), 4)
        for agent in base_weights
    }

    ml_metrics: dict[str, Any] = {}
    metrics_path = Path("data/models/signal_model_metrics.json")
    if metrics_path.exists():
        try:
            ml_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    plan: dict[str, Any] = {
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "old_weights": base_weights,
        "new_weights": new_weights,
        "weight_deltas": weight_deltas,
        "parameter_overrides": parameter_deltas,
        "regime_boost_overrides": regime_boost_deltas,
        "promoted": promoted,
        "blocked_reason": None if promoted else blocked_reason,
        "walk_forward": {
            "oos_return": wf_result.oos_return if wf_result else 0.0,
            "oos_sharpe": wf_result.oos_sharpe if wf_result else 0.0,
            "oos_max_dd": wf_result.oos_max_dd if wf_result else 0.0,
            "baseline_sharpe": wf_result.baseline_sharpe if wf_result else 0.0,
            "sharpe_delta": sharpe_delta,
            "historical_files": len(historical_files),
            "symbol_count": wf_result.symbol_count if wf_result else 0,
        },
        "semantic_keys": memory.semantic_key_count(),
        "trade_count": memory.trade_count(),
        "agent_audit_summary": {
            "trade_count": audit.get("trade_count", 0),
            "recommendations": len(audit.get("recommendations", [])),
        },
        "agent_health_status": agent_health_status,
        "ml_model_metrics": ml_metrics,
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
