"""Load adaptation_plan.json and apply promoted weights on engine start."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/adaptation_plan.json")


def load_adaptation_plan(path: Path | str | None = None) -> dict[str, Any] | None:
    p = Path(path or DEFAULT_PATH)
    if not p.exists():
        logger.info("No adaptation plan at %s", p)
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded adaptation plan from %s", p)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load adaptation plan: %s", exc)
        return None


def apply_adaptation_to_config(config: Any, plan: dict[str, Any] | None) -> dict[str, float]:
    """Merge promoted agent weights/params/boosts into runtime config. Returns applied weights."""
    if not plan:
        return {}

    if not plan.get("promoted"):
        return {}

    promoted = plan.get("new_weights") or plan.get("promoted_weights") or plan.get("weights") or {}

    applied: dict[str, float] = {}
    for agent_name, weight in promoted.items():
        if agent_name not in config.agents:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        config.agents[agent_name]["weight"] = w
        applied[agent_name] = w

    param_overrides = plan.get("parameter_overrides") or {}
    for agent_name, params in param_overrides.items():
        if agent_name not in config.agents or not isinstance(params, dict):
            continue
        for key, value in params.items():
            base = config.agents[agent_name].get(key)
            if base is None:
                continue
            try:
                if isinstance(base, bool):
                    continue
                if isinstance(base, int):
                    config.agents[agent_name][key] = int(round(float(base) + float(value)))
                else:
                    config.agents[agent_name][key] = float(base) + float(value)
            except (TypeError, ValueError):
                continue

    boost_overrides = plan.get("regime_boost_overrides") or {}
    for regime, agents in boost_overrides.items():
        if regime not in config.regime_boosts or not isinstance(agents, dict):
            continue
        for agent_name, delta in agents.items():
            if agent_name not in config.regime_boosts[regime]:
                continue
            try:
                config.regime_boosts[regime][agent_name] = round(
                    float(config.regime_boosts[regime][agent_name]) + float(delta), 3,
                )
            except (TypeError, ValueError):
                continue

    if applied:
        logger.info("Applied adaptation weights: %s", applied)
        if param_overrides:
            logger.info("Applied parameter overrides for: %s", list(param_overrides.keys()))
        if boost_overrides:
            logger.info("Applied regime boost overrides for regimes: %s", list(boost_overrides.keys()))
        try:
            from src.utils.logger import log_event

            log_event(
                "adaptation_weights_applied",
                weights=applied,
                parameter_overrides=param_overrides,
                regime_boost_overrides=boost_overrides,
            )
        except Exception:
            pass

    return applied
