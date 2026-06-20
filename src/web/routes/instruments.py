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
        })

    return {"instruments": items, "count": len(items)}
