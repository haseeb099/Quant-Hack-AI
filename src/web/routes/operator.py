"""Operator runbook and Northflank deploy status API."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.operator.preflight import run_preflight
from src.operator.runbook import build_operator_runbook, northflank_deploy_status
from src.operator.alerts import ALERT_LOG_PATH
from src.operator.snapshot_store import read_history, read_snapshot
from src.operator.verification import get_verification_status, run_verification
from src.operator.watchdog import run_operator_watchdog_cycle
from src.utils.logger import instrument_span, log_event

router = APIRouter(tags=["operator"])


@router.get("/api/operator/runbook")
@instrument_span("quantai.operator.runbook")
def get_operator_runbook() -> dict:
    return build_operator_runbook()


@router.get("/api/operator/preflight")
@instrument_span("quantai.operator.preflight")
def get_operator_preflight(
    zmq_only: bool = Query(default=True),
    with_cycle: bool = Query(default=False),
    deep: bool = Query(default=False),
) -> dict:
    return run_preflight(zmq_only=zmq_only, with_cycle=with_cycle, deep=deep)


@router.get("/api/operator/snapshot")
@instrument_span("quantai.operator.snapshot")
def get_operator_snapshot() -> dict:
    snapshot = read_snapshot()
    if snapshot is None:
        return {"available": False, "snapshot": None}
    return {"available": True, "snapshot": snapshot}


@router.get("/api/operator/snapshot/history")
@instrument_span("quantai.operator.snapshot_history")
def get_operator_snapshot_history(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    history = read_history(limit=limit)
    return {"count": len(history), "history": history}


class WatchdogTriggerRequest(BaseModel):
    confirm: bool = Field(default=False)
    zmq_only: bool = Field(default=False)


@router.get("/api/operator/alerts")
@instrument_span("quantai.operator.alerts")
def get_operator_alerts(limit: int = Query(default=20, ge=1, le=200)) -> dict:
    if not ALERT_LOG_PATH.exists():
        return {"available": False, "count": 0, "alerts": []}
    lines: list[str] = []
    with open(ALERT_LOG_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                lines.append(line)

    alerts_out: list[dict] = []
    for raw in lines[-limit:]:
        try:
            alerts_out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return {"available": True, "count": len(alerts_out), "alerts": alerts_out}


@router.post("/api/operator/watchdog/trigger")
@instrument_span("quantai.operator.watchdog_trigger")
def trigger_operator_watchdog(body: WatchdogTriggerRequest) -> dict:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to run an operator watchdog cycle",
        )
    snapshot = run_operator_watchdog_cycle(zmq_only=body.zmq_only, persist=True)
    log_event("operator_watchdog_trigger", status=snapshot.get("status"))
    return {"ok": True, "snapshot": snapshot}


@router.get("/api/deploy/northflank")
@instrument_span("quantai.deploy.northflank")
def get_northflank_deploy_status() -> dict:
    return northflank_deploy_status()


class VerificationRunRequest(BaseModel):
    confirm: bool = Field(default=False)
    quick: bool = Field(default=True)


@router.get("/api/operator/verification")
@instrument_span("quantai.operator.verification")
def get_operator_verification() -> dict:
    return get_verification_status()


@router.post("/api/operator/verification/run")
@instrument_span("quantai.operator.verification_run")
def run_operator_verification(body: VerificationRunRequest) -> dict:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to run automated verification (includes pytest)",
        )
    result = run_verification(quick=body.quick, persist=True)
    log_event("operator_verification_run", ready=result["ready"], mode=result["mode"])
    return {"ok": True, **result}
