"""Competition scoring endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.utils.logger import instrument_span
from src.web.launch_readiness import evaluate_launch_readiness
from src.web.routes._helpers import compute_competition_score
from src.web.runtime_state import read_state

router = APIRouter(tags=["competition"])


@router.get("/api/competition-score")
def get_competition_score() -> dict:
    state = read_state()
    return compute_competition_score(state)


@router.get("/api/competition/launch-readiness")
@instrument_span("quantai.dashboard.launch_readiness")
def get_launch_readiness() -> dict:
    """Go/no-go checklist for competition launch."""
    return evaluate_launch_readiness(read_state())
