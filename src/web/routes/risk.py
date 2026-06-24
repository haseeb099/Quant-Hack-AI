"""Risk and compliance endpoints."""



from __future__ import annotations



from fastapi import APIRouter, Query



from src.engine.config import load_yaml

from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate

from src.utils.logger import instrument_span

from src.web.runtime_state import read_state



router = APIRouter(tags=["risk"])





def _flatten_risk(risk: dict) -> dict:

    """Normalize nested margin dict from engine snapshots for REST consumers."""

    margin = risk.get("margin")

    if isinstance(margin, dict):

        risk = {

            **risk,

            "margin_state": margin.get("action", risk.get("margin_state", "normal")),

            "margin_usage_pct": margin.get("margin_usage_pct", risk.get("margin_usage_pct", 0)),

            "effective_leverage": margin.get("effective_leverage", risk.get("effective_leverage", 0)),

            "concentration_pct": margin.get("concentration_pct", risk.get("concentration_pct", 0)),

            "margin_level_pct": margin.get("margin_level_pct", risk.get("margin_level_pct")),

            "net_directional_pct": margin.get("net_directional_pct", risk.get("net_directional_pct", 0)),

        }

        risk.pop("margin", None)

    return risk





@router.get("/api/risk")

@instrument_span("quantai.risk.summary")

def get_risk() -> dict:

    state = read_state()

    risk = _flatten_risk(state.get("risk", {}))

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

            "net_directional_cap": risk_cfg.get("net_directional", {}).get("internal_cap", 0.85),

            "stop_out_level_pct": risk_cfg.get("margin", {}).get("stop_out_level_pct", 30),

        },

        "events": state.get("risk_events", []),
        "violations": risk.get("violations", []),

    }





@router.get("/api/risk/check-trade")

@instrument_span("quantai.risk.check_trade")

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

