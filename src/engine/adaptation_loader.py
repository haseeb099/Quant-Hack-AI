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
    """Merge promoted agent weights into runtime config. Returns applied weights."""
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

    if applied:
        logger.info("Applied adaptation weights: %s", applied)
        try:
            from src.utils.logger import get_logfire

            lf = get_logfire()
            if lf:
                lf.info("adaptation_weights_applied", weights=applied)
        except Exception:
            pass

    return applied
