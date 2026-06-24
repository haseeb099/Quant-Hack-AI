"""Trading control endpoints — pause, close, modify, manual orders."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.web.engine_registry import control_state, get_connector, get_engine
from src.web.runtime_state import append_risk_event, read_state, write_state
from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["control"])

FILTERS_PATH = Path("data/live_competition_filters.json")
ALLOWED_FILTER_KEYS = frozenset({
    "blocked_symbols",
    "max_new_entries_per_cycle",
    "min_confidence",
    "prefer_symbols",
    "max_fx_shorts_per_cycle",
    "max_chf_entries_per_cycle",
    "min_consensus_agents",
    "fx_min_consensus_agents",
    "crypto_min_consensus_agents",
    "buy_min_confidence_fx",
    "buy_min_confidence_metals",
    "block_long_rsi_above",
    "block_short_rsi_below",
    "bullish_bias_short_min_confidence",
    "bearish_bias_long_min_confidence",
    "macro_metal_short_min_confidence",
    "metals_mr_short_requires_trend_confirm",
    "trending_min_consensus_agents",
    "trending_min_confidence",
    "min_trend_surfer_for_overbought_long",
    "min_trend_surfer_for_oversold_short",
    "require_technical_agent",
    "technical_agents",
    "block_agent_in_regime",
    "block_ml_disagreement_on_crypto",
    "time_stop_bars",
    "time_stop_m15_bars",
    "time_stop_min_r",
    "enable_trailing",
    "a_plus_bypass",
    "crypto_min_lot_bump",
    "round_objective",
    "notes",
    "source",
})


class CompetitionFiltersBody(BaseModel):
    blocked_symbols: list[str] = Field(default_factory=list)
    max_new_entries_per_cycle: int = Field(ge=1, le=20)
    min_confidence: float = Field(ge=0.0, le=1.0)
    prefer_symbols: list[str] = Field(default_factory=list)
    max_fx_shorts_per_cycle: int | None = Field(default=None, ge=0, le=10)
    max_chf_entries_per_cycle: int | None = Field(default=None, ge=0, le=10)
    min_consensus_agents: int | None = Field(default=None, ge=1, le=6)
    fx_min_consensus_agents: int | None = Field(default=None, ge=1, le=6)
    crypto_min_consensus_agents: int | None = Field(default=None, ge=1, le=6)
    buy_min_confidence_fx: float | None = Field(default=None, ge=0.0, le=1.0)
    buy_min_confidence_metals: float | None = Field(default=None, ge=0.0, le=1.0)
    block_long_rsi_above: float | None = Field(default=None, ge=0.0, le=100.0)
    bullish_bias_short_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_metal_short_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metals_mr_short_requires_trend_confirm: bool | None = None
    trending_min_consensus_agents: int | None = Field(default=None, ge=1, le=6)
    trending_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    time_stop_m15_bars: int | None = Field(default=None, ge=1, le=48)
    block_agent_in_regime: dict[str, list[str]] | None = None
    round_objective: str | None = None
    notes: str | None = None
    source: str | None = None

    @field_validator("blocked_symbols", "prefer_symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for sym in values:
            sym = sym.strip().upper().replace("_", "/")
            if "/" not in sym and len(sym) == 6:
                sym = f"{sym[:3]}/{sym[3:]}"
            cleaned.append(sym)
        return cleaned


class ModifyPositionBody(BaseModel):
    sl: float | None = None
    tp: float | None = None


class ManualTradeBody(BaseModel):
    symbol: str
    direction: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    volume: float = Field(gt=0, le=100)
    sl: float | None = None
    tp: float | None = None


def _require_engine() -> Any:
    engine = get_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Trading engine not attached — start with python main.py --with-dashboard",
        )
    return engine


def _log_operator_action(action: str, message: str) -> None:
    state = read_state()
    append_risk_event(state, action, message, "info")
    write_state(state)


def _result_response(result: dict[str, Any], action: str) -> dict[str, Any]:
    ok = result.get("status") in ("ok", "simulated")
    if ok:
        _log_operator_action(f"OPERATOR_{action}", f"{action} succeeded")
    return {
        "ok": ok,
        "status": result.get("status", "error"),
        "message": result.get("message", ""),
        "result": result,
    }


@router.get("/api/competition/filters")
def get_competition_filters() -> dict[str, Any]:
    if not FILTERS_PATH.exists():
        return {"filters": {}, "path": str(FILTERS_PATH)}
    with open(FILTERS_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    return {"filters": data, "path": str(FILTERS_PATH)}


@router.post("/api/competition/filters")
def update_competition_filters(body: CompetitionFiltersBody) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if FILTERS_PATH.exists():
        with open(FILTERS_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
            if isinstance(raw, dict):
                existing = raw

    payload = body.model_dump(exclude_none=True)
    for key in payload:
        if key not in ALLOWED_FILTER_KEYS:
            raise HTTPException(status_code=400, detail=f"Disallowed filter key: {key}")

    merged = {**existing, **payload}
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    FILTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FILTERS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")

    _log_operator_action("COMPETITION_FILTERS", "Operator updated live competition filters")
    return {"ok": True, "filters": merged}


@router.get("/api/engine/open_trades")
def get_engine_open_trades() -> dict[str, Any]:
    engine = get_engine()
    if engine is None:
        return {"count": 0, "tickets": [], "trades": {}}
    return engine.get_open_trades()


@router.get("/api/control/state")
def get_control_state() -> dict[str, Any]:
    return control_state()


@router.post("/api/engine/pause")
def pause_engine() -> dict[str, Any]:
    engine = _require_engine()
    engine.pause_trading()
    _log_operator_action("ENGINE_PAUSE", "Operator paused new trade entries")
    return {"ok": True, "engine_paused": True}


@router.post("/api/engine/resume")
def resume_engine() -> dict[str, Any]:
    engine = _require_engine()
    engine.resume_trading()
    _log_operator_action("ENGINE_RESUME", "Operator resumed trade entries")
    return {"ok": True, "engine_paused": False}


@router.post("/api/engine/run-cycle")
def run_cycle_now() -> dict[str, Any]:
    engine = _require_engine()
    if engine.cycle_in_progress:
        raise HTTPException(status_code=409, detail="Cycle already in progress")
    result = engine.force_run_cycle()
    if result.get("status") == "busy":
        raise HTTPException(status_code=409, detail="Cycle already in progress")
    _log_operator_action("ENGINE_RUN_CYCLE", "Operator triggered immediate cycle")
    return {"ok": True, **result}


@router.post("/api/bridge/reconnect")
def reconnect_bridge() -> dict[str, Any]:
    engine = get_engine()
    if engine is not None:
        result = engine.operator_reconnect_mt5()
    else:
        connector = get_connector()
        ok = connector.reconnect()
        result = {
            "status": "ok" if ok else "error",
            "connected": ok,
            "message": connector.last_error,
        }
    _log_operator_action("BRIDGE_RECONNECT", result.get("message", "Reconnect attempted"))
    return {"ok": result.get("status") == "ok", **result}


@router.post("/api/positions/{ticket}/close")
def close_position(ticket: int) -> dict[str, Any]:
    engine = get_engine()
    if engine is not None:
        result = engine.operator_close_position(ticket)
    else:
        result = get_connector().close_position(ticket)
    resp = _result_response(result, f"CLOSE_{ticket}")
    if not resp["ok"]:
        raise HTTPException(status_code=502, detail=resp.get("message") or "Close failed")
    return resp


@router.post("/api/positions/close-all")
def close_all_positions() -> dict[str, Any]:
    engine = get_engine()
    if engine is not None:
        result = engine.operator_close_all()
    else:
        result = get_connector().close_all()
    resp = _result_response(result, "CLOSE_ALL")
    if not resp["ok"]:
        raise HTTPException(status_code=502, detail=resp.get("message") or "Close all failed")
    return resp


@router.patch("/api/positions/{ticket}")
def modify_position(ticket: int, body: ModifyPositionBody) -> dict[str, Any]:
    if body.sl is None and body.tp is None:
        raise HTTPException(status_code=400, detail="Provide sl and/or tp")
    engine = get_engine()
    if engine is not None:
        result = engine.operator_modify_position(ticket, sl=body.sl, tp=body.tp)
    else:
        result = get_connector().modify_position(ticket, sl=body.sl, tp=body.tp)
    resp = _result_response(result, f"MODIFY_{ticket}")
    if not resp["ok"]:
        raise HTTPException(status_code=502, detail=resp.get("message") or "Modify failed")
    return resp


@router.post("/api/trades/manual")
def manual_trade(body: ManualTradeBody) -> dict[str, Any]:
    direction = body.direction.upper()
    gate = get_pre_trade_gate()
    request = TradeCheckRequest(
        symbol=body.symbol.strip(),
        direction=direction,
        volume=body.volume,
        sl=body.sl,
        tp=body.tp,
    )

    engine = get_engine()
    if engine is not None:
        check = gate.evaluate_from_engine(engine, request)
    else:
        state = read_state()
        if state.get("mode") == "live":
            raise HTTPException(
                status_code=503,
                detail="Trading engine not attached — start with python main.py --with-dashboard",
            )
        check = gate.evaluate_from_state(state, request)

    if not check.allowed:
        detail = {
            "message": "Trade blocked by risk constitution",
            **check.to_dict(),
        }
        raise HTTPException(status_code=422, detail=detail)

    if engine is not None:
        result = engine.operator_manual_trade(
            symbol=body.symbol,
            direction=direction,
            volume=body.volume,
            sl=body.sl,
            tp=body.tp,
            skip_risk_check=True,
        )
    else:
        connector = get_connector()
        if not connector.is_connected:
            connector.connect()
        result = connector.send_trade(
            symbol=body.symbol,
            direction=direction,
            volume=body.volume,
            sl=body.sl,
            tp=body.tp,
        )
    resp = _result_response(result, f"MANUAL_{direction}_{body.symbol}")
    if not resp["ok"]:
        raise HTTPException(status_code=502, detail=resp.get("message") or "Trade failed")
    return {**resp, "risk_check": check.to_dict()}
