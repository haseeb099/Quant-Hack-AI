"""Market intelligence API routes."""

from __future__ import annotations

from fastapi import APIRouter

from src.engine.config import QuantAIConfig
from src.intelligence.market_intelligence import MarketIntelligenceService
from src.web.runtime_state import read_state

router = APIRouter(tags=["intelligence"])
_service: MarketIntelligenceService | None = None


def _get_service() -> MarketIntelligenceService:
    global _service
    if _service is None:
        _service = MarketIntelligenceService()
    return _service


@router.get("/api/intelligence/snapshot")
def get_intelligence_snapshot() -> dict:
    state = read_state()
    intel = state.get("intelligence")
    if intel:
        return intel
    service = _get_service()
    if service.enabled:
        symbols = QuantAIConfig.load().active_symbols
        service.refresh(symbols)
        return service.snapshot()
    return {"enabled": False}


@router.get("/api/intelligence/calendar")
def get_calendar(hours: int = 8) -> dict:
    service = _get_service()
    service.calendar.refresh()
    return {"events": service.upcoming_events(hours), "enabled": service.enabled}


@router.get("/api/intelligence/sentiment")
def get_all_sentiment() -> dict:
    state = read_state()
    intel = state.get("intelligence", {})
    return {
        "enabled": intel.get("enabled", False),
        "sentiment": intel.get("sentiment", {}),
        "macro": intel.get("macro", {}),
    }


@router.get("/api/intelligence/sentiment/{symbol}")
def get_symbol_sentiment(symbol: str) -> dict:
    state = read_state()
    intel = state.get("intelligence", {})
    sentiment = (intel.get("sentiment") or {}).get(symbol)
    if sentiment:
        return {"symbol": symbol, **sentiment}
    service = _get_service()
    service.refresh([symbol], force=True)
    snap = service.get_sentiment(symbol)
    return snap.to_dict() if snap else {"symbol": symbol, "score": 0, "confidence": 0, "summary": "No data"}
