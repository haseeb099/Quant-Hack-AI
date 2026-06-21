"""Trading control endpoints — pause, close, modify, manual orders."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.web.engine_registry import control_state, get_connector, get_engine
from src.web.runtime_state import append_risk_event, read_state, write_state
from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["control"])


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
        check = gate.evaluate_from_state(read_state(), request)

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
