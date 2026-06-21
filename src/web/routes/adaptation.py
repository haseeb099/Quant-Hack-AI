"""Between-round adaptation API — view plan and trigger adapt_round."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.engine.config import QuantAIConfig
from src.learning.adaptation_service import load_adaptation_plan, run_adaptation
from src.utils.logger import instrument_span, log_event
from src.web.between_round import adaptation_status, can_run_adaptation
from src.web.runtime_state import read_state

router = APIRouter(tags=["adaptation"])


class AdaptationRunRequest(BaseModel):
    phase: str | None = None
    data_dir: str = Field(default="data/historical")
    confirm: bool = False


@router.get("/api/adaptation/plan")
def get_adaptation_plan() -> dict:
    plan = load_adaptation_plan()
    if plan is None:
        return {"plan": None, "exists": False}
    return {"plan": plan, "exists": True}


@router.get("/api/adaptation/status")
@instrument_span("quantai.adaptation.status")
def get_adaptation_status() -> dict:
    state = read_state()
    config = QuantAIConfig.load(phase=state.get("phase", "round1"))
    current_weights = {
        name: float(cfg.get("weight", 0.25))
        for name, cfg in config.agents.items()
        if name != "meta_orchestrator"
    }
    plan = load_adaptation_plan()
    return {
        **adaptation_status(state),
        "current_weights": current_weights,
        "plan": plan,
        "plan_exists": plan is not None,
        "last_promoted": bool(plan.get("promoted")) if plan else False,
    }


@router.post("/api/adaptation/run")
@instrument_span("quantai.adaptation.run")
def run_adaptation_endpoint(body: AdaptationRunRequest) -> dict:
    state = read_state()
    allowed, reason = can_run_adaptation(state)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to run between-round adaptation",
        )

    phase = body.phase or str(state.get("phase", "round1"))
    try:
        plan = run_adaptation(phase=phase, data_dir=body.data_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Adaptation failed: {exc}") from exc

    log_event(
        "adaptation_run",
        phase=phase,
        promoted=plan.get("promoted"),
        trade_count=plan.get("trade_count"),
    )

    return {
        "ok": True,
        "plan": plan,
        "message": (
            "Weights promoted — restart engine to apply"
            if plan.get("promoted")
            else "Plan written — weights not promoted (OOS gate failed)"
        ),
    }
