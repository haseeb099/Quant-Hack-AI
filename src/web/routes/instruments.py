"""Competition instruments endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.engine.config import load_yaml
from src.web.runtime_state import read_state

router = APIRouter(tags=["instruments"])


@router.get("/api/instruments")
def get_instruments() -> dict:
    state = read_state()
    runtime_instruments = state.get("instruments", {})
    instruments_cfg = load_yaml("instruments.yaml").get("instruments", [])

    items = []
    for inst in instruments_cfg:
        symbol = inst.get("symbol", "")
        runtime = runtime_instruments.get(symbol, {})
        items.append({
            "symbol": symbol,
            "category": inst.get("category", ""),
            "bias": inst.get("bias", ""),
            "allocation": inst.get("allocation", 0),
            "primary_agent": inst.get("primary_agent", ""),
            "active": inst.get("active", True),
            "session_active": runtime.get("session_active", True),
            "last_regime": runtime.get("last_regime", "unknown"),
            "last_decision": runtime.get("last_decision"),
            "bid": runtime.get("bid"),
            "ask": runtime.get("ask"),
            "mid": runtime.get("mid"),
            "spread": runtime.get("spread"),
            "change_pct": runtime.get("change_pct"),
            "tick_age_ms": runtime.get("tick_age_ms"),
            "market_health": runtime.get("market_health"),
            "bar_age_sec": runtime.get("bar_age_sec"),
        })

    return {"instruments": items, "count": len(items)}
