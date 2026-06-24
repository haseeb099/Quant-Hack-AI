"""Open positions endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.risk.account_profile import position_notional_from_dict
from src.web.runtime_state import read_state

router = APIRouter(tags=["positions"])


@router.get("/api/positions")
def get_positions() -> dict:
    state = read_state()
    positions = state.get("positions", [])
    total_exposure = 0.0
    total_pnl = 0.0
    for p in positions:
        notional_raw = p.get("notional")
        if notional_raw is not None:
            total_exposure += abs(float(notional_raw))
        else:
            contract = float(p.get("contract_size", 1))
            total_exposure += position_notional_from_dict(p, contract)
        total_pnl += float(p.get("profit", p.get("unrealized_pnl", 0)))
    return {
        "positions": positions,
        "count": len(positions),
        "total_exposure": total_exposure,
        "total_unrealized_pnl": total_pnl,
    }
