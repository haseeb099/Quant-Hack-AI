"""Demo walkthrough and technology prize API."""

from __future__ import annotations

from fastapi import APIRouter

from src.demo.technology_prize import evaluate_technology_prize_checklist
from src.demo.walkthrough import build_demo_walkthrough
from src.utils.logger import instrument_span

router = APIRouter(tags=["demo"])


@router.get("/api/demo/walkthrough")
@instrument_span("quantai.demo.walkthrough")
def get_demo_walkthrough() -> dict:
    return build_demo_walkthrough()


@router.get("/api/prize/technology-checklist")
@instrument_span("quantai.prize.technology")
def get_technology_prize_checklist() -> dict:
    return evaluate_technology_prize_checklist()
