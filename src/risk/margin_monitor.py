"""Margin and leverage monitoring with enforceable actions."""

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
    block_new_trades: bool = False
    size_multiplier: float = 1.0
    leverage_haircut: float = 1.0
    close_worst_loser: bool = False
    reduce_positions_pct: float = 0.0


class MarginMonitor:
    """Tracks margin, leverage, and concentration against frozen caps."""

    def __init__(
        self,
        margin_cfg: dict[str, Any],
        leverage_cfg: dict[str, Any],
        conc_cfg: dict[str, Any],
        drawdown_cfg: dict[str, Any] | None = None,
    ) -> None:
        self.margin_cfg = margin_cfg
        self.leverage_cfg = leverage_cfg
        self.conc_cfg = conc_cfg
        self.drawdown_cfg = drawdown_cfg or {}
        self._session_start_equity: float | None = None
        self._daily_loss_halt = False

    def reset_session(self, equity: float) -> None:
        self._session_start_equity = equity
        self._daily_loss_halt = False

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
        block = False
        size_mult = 1.0
        leverage_haircut = 1.0
        close_worst = False
        reduce_pct = 0.0

        emergency_pct = self.margin_cfg.get("emergency_pct", 0.88)
        action_pct = self.margin_cfg.get("action_pct", 0.80)
        lev_max = self.leverage_cfg.get("max", 20)
        lev_warning = self.leverage_cfg.get("warning", 15)
        lev_hard = self.leverage_cfg.get("hard_stop", 25)
        conc_max = self.conc_cfg.get("max_pct", 0.40)
        conc_hard = self.conc_cfg.get("hard_stop_pct", 0.50)

        # Daily loss limit
        daily_limit = self.drawdown_cfg.get("daily_loss_limit", 0.05)
        if self._session_start_equity and self._session_start_equity > 0:
            daily_loss = (self._session_start_equity - equity) / self._session_start_equity
            if daily_loss >= daily_limit:
                self._daily_loss_halt = True
                actions.append("Daily loss 5% — halt new trades")
                block = True
                size_mult = min(size_mult, 0.25)
            elif daily_loss >= daily_limit * 0.75:
                size_mult = min(size_mult, 0.25)
                actions.append("Daily loss approaching limit — reduce size 75%")

        if margin_pct >= emergency_pct:
            actions.append("EMERGENCY: block entries + close worst loser")
            block = True
            close_worst = True
        elif margin_pct >= action_pct:
            actions.append("Reduce new trade size 50%")
            size_mult = min(size_mult, 0.5)
            reduce_pct = max(reduce_pct, 0.25)

        if leverage >= lev_hard:
            actions.append("Leverage hard stop — block new trades")
            block = True
        elif leverage >= lev_max:
            actions.append("Leverage at max — reduce sizing")
            size_mult = min(size_mult, 0.5)
            block = True
        elif leverage > lev_warning:
            # Haircut Kelly proportionally above warning threshold
            excess = (leverage - lev_warning) / max(lev_max - lev_warning, 1e-9)
            leverage_haircut = max(0.5, 1.0 - excess * 0.5)
            actions.append(f"Leverage haircut {leverage_haircut:.0%}")

        if largest_position_pct >= conc_hard:
            actions.append("Concentration hard stop")
            block = True
        elif largest_position_pct >= conc_max:
            actions.append("Concentration above 40% — block same symbol/cluster")
            block = True

        action = actions[0] if actions else "normal"
        return MarginState(
            margin_usage_pct=margin_pct,
            effective_leverage=leverage,
            concentration_pct=largest_position_pct,
            action=action,
            message="; ".join(actions) if actions else "All metrics within limits",
            block_new_trades=block or self._daily_loss_halt,
            size_multiplier=size_mult,
            leverage_haircut=leverage_haircut,
            close_worst_loser=close_worst,
            reduce_positions_pct=reduce_pct,
        )

    @property
    def daily_loss_halt(self) -> bool:
        return self._daily_loss_halt

    def concentration_blocks_symbol(self, symbol: str, concentration_pct: float) -> bool:
        """Block new trades in same symbol when concentration exceeds max cap."""
        max_pct = self.conc_cfg.get("max_pct", 0.40)
        return concentration_pct >= max_pct
