"""Margin and leverage monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MarginState:
    margin_usage_pct: float
    effective_leverage: float
    concentration_pct: float
    action: str
    message: str


class MarginMonitor:
    """Tracks margin, leverage, and concentration against frozen caps."""

    def __init__(self, margin_cfg: dict[str, Any], leverage_cfg: dict[str, Any], conc_cfg: dict[str, Any]) -> None:
        self.margin_cfg = margin_cfg
        self.leverage_cfg = leverage_cfg
        self.conc_cfg = conc_cfg

    def check(
        self,
        equity: float,
        used_margin: float,
        gross_exposure: float,
        largest_position_pct: float,
    ) -> MarginState:
        margin_pct = used_margin / (equity + 1e-9)
        leverage = gross_exposure / (equity + 1e-9)
        actions: list[str] = []

        if margin_pct >= self.margin_cfg.get("emergency_pct", 0.88):
            actions.append("EMERGENCY: close all positions")
        elif margin_pct >= self.margin_cfg.get("action_pct", 0.80):
            actions.append("Reduce positions 50%")

        if leverage >= self.leverage_cfg.get("hard_stop", 25):
            actions.append("Leverage hard stop — block new trades")
        elif leverage >= self.leverage_cfg.get("max", 20):
            actions.append("Leverage at max — reduce sizing")

        if largest_position_pct >= self.conc_cfg.get("hard_stop_pct", 0.50):
            actions.append("Concentration hard stop")

        action = actions[0] if actions else "normal"
        return MarginState(
            margin_usage_pct=margin_pct,
            effective_leverage=leverage,
            concentration_pct=largest_position_pct,
            action=action,
            message="; ".join(actions) if actions else "All metrics within limits",
        )
