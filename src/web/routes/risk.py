"""Risk and compliance endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.engine.config import load_yaml
from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate
from src.web.runtime_state import read_state

router = APIRouter(tags=["risk"])


@router.get("/api/risk")
def get_risk() -> dict:
    state = read_state()
    risk = state.get("risk", {})
    risk_cfg = load_yaml("risk.yaml").get("risk", {})
    return {
        **risk,
        "tiers": {
            "normal_max": risk_cfg.get("drawdown", {}).get("normal_max", 0.05),
            "elevated_max": risk_cfg.get("drawdown", {}).get("elevated_max", 0.10),
            "warning_max": risk_cfg.get("drawdown", {}).get("warning_max", 0.12),
            "critical_max": risk_cfg.get("drawdown", {}).get("critical_max", 0.15),
            "emergency_close": risk_cfg.get("drawdown", {}).get("emergency_close", 0.15),
        },
        "caps": {
            "margin_emergency_pct": risk_cfg.get("margin", {}).get("emergency_pct", 0.88),
            "leverage_max": risk_cfg.get("leverage", {}).get("max", 20),
            "concentration_max_pct": risk_cfg.get("concentration", {}).get("max_pct", 0.40),
        },
        "events": state.get("risk_events", []),
    }


@router.get("/api/risk/check-trade")
def check_trade(
    symbol: str = Query(..., min_length=3),
    direction: str = Query(..., pattern="^(BUY|SELL|buy|sell)$"),
    volume: float = Query(..., gt=0, le=100),
    sl: float | None = None,
    tp: float | None = None,
    price: float | None = Query(None, gt=0),
) -> dict:
    """Pre-trade risk check with structured blockers (manual orders + copilot)."""
    state = read_state()
    request = TradeCheckRequest(
        symbol=symbol.strip(),
        direction=direction.upper(),
        volume=volume,
        sl=sl,
        tp=tp,
        price=price,
    )
    result = get_pre_trade_gate().evaluate_from_state(state, request)
    return result.to_dict()
