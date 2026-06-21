"""Operator runbook and Northflank deploy status API."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.operator.preflight import run_preflight
from src.operator.runbook import build_operator_runbook, northflank_deploy_status
from src.utils.logger import instrument_span

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
