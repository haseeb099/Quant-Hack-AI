"""Competition scoring endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.web.routes._helpers import compute_competition_score
from src.web.runtime_state import read_state

router = APIRouter(tags=["competition"])


@router.get("/api/competition-score")
def get_competition_score() -> dict:
    state = read_state()
    return compute_competition_score(state)
