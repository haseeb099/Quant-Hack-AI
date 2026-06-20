"""Open positions endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["positions"])


@router.get("/api/positions")
def get_positions() -> dict:
    state = read_state()
    positions = state.get("positions", [])
    total_exposure = sum(
        abs(p.get("volume", 0) * p.get("price_open", 0))
        for p in positions
    )
    total_pnl = sum(p.get("profit", 0) for p in positions)
    return {
        "positions": positions,
        "count": len(positions),
        "total_exposure": total_exposure,
        "total_unrealized_pnl": total_pnl,
    }
