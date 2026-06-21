"""Open positions endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["positions"])


@router.get("/api/positions")
def get_positions() -> dict:
    state = read_state()
    positions = state.get("positions", [])
    total_exposure = 0.0
    total_pnl = 0.0
    for p in positions:
        lots = float(p.get("volume", p.get("lots", p.get("size", 0))))
        entry = float(p.get("price_open", p.get("entry", 0)))
        total_exposure += abs(lots * entry)
        total_pnl += float(p.get("profit", p.get("unrealized_pnl", 0)))
    return {
        "positions": positions,
        "count": len(positions),
        "total_exposure": total_exposure,
        "total_unrealized_pnl": total_pnl,
    }
