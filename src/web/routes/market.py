"""Live market data endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.web.runtime_state import read_state

router = APIRouter(tags=["market"])


@router.get("/api/market/live")
def get_market_live() -> dict:
    state = read_state()
    market = state.get("market", {})
    instruments = state.get("instruments", {})
    live_instruments = {
        sym: {
            k: data[k]
            for k in (
                "bid",
                "ask",
                "mid",
                "spread",
                "change_pct",
                "tick_age_ms",
                "market_health",
                "bar_age_sec",
                "drift_atr",
                "last_close",
            )
            if k in data
        }
        for sym, data in instruments.items()
        if isinstance(data, dict)
    }
    return {
        "last_tick_at": market.get("last_tick_at"),
        "last_tick_age_ms": market.get("last_tick_age_ms"),
        "instruments": live_instruments,
        "count": len(live_instruments),
    }
