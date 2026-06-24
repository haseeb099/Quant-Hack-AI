"""Convert account-currency risk amount to MT5 lot volume."""

from __future__ import annotations

import math

from src.risk.account_profile import position_notional

__all__ = ["position_notional", "pnl_pct", "risk_to_lots"]


def pnl_pct(profit: float, volume: float, entry: float, contract_size: float) -> float:
    """Position PnL as fraction of notional exposure."""
    notional = position_notional(volume, contract_size, entry)
    return profit / max(notional, 1e-9)


def risk_to_lots(
    risk_amount: float,
    entry: float,
    stop_loss: float | None,
    contract_size: float,
    volume_min: float,
    volume_step: float,
    volume_max: float,
) -> float:
    """Map dollar risk budget to exchange lot size."""
    if risk_amount <= 0 or entry <= 0 or contract_size <= 0:
        return 0.0

    sl_dist = abs(entry - stop_loss) if stop_loss is not None else entry * 0.01
    if sl_dist <= 0:
        return 0.0

    lots = risk_amount / (sl_dist * contract_size)
    lots = min(lots, volume_max)

    if volume_step > 0:
        lots = math.floor(lots / volume_step) * volume_step

    if lots < volume_min:
        min_lot_risk = volume_min * sl_dist * contract_size
        if min_lot_risk > risk_amount:
            return 0.0
        return volume_min if risk_amount > 0 else 0.0
    return round(lots, 8)
