"""Convert account-currency risk amount to MT5 lot volume."""

from __future__ import annotations

import math


def risk_to_lots(
    risk_amount: float,
    entry: float,
    stop_loss: float | None,
    contract_size: float,
    volume_min: float,
    volume_step: float,
    volume_max: float,
) -> float:
    """Map dollar/ETH risk budget to exchange lot size."""
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
        # Small accounts: use broker minimum when risk budget is positive
        return volume_min if risk_amount > 0 else 0.0
    return round(lots, 8)
