"""Operator runbook and Northflank deploy status API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.operator.preflight import run_preflight
from src.operator.runbook import build_operator_runbook, northflank_deploy_status
from src.operator.verification import get_verification_status, run_verification
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
) -> dict:
    return run_preflight(zmq_only=zmq_only, with_cycle=with_cycle)


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
