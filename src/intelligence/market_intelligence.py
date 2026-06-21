"""Market intelligence service — orchestrates calendar, news, sentiment, macro."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from src.engine.config import CONFIG_DIR
from src.intelligence.calendar_monitor import CalendarMonitor
from src.intelligence.event_risk_gate import EventRiskGate
from src.intelligence.macro_overlay import MacroOverlay
from src.intelligence.models import EventGateResult, MacroRegime, SentimentSnapshot
from src.intelligence.news_ingestor import NewsIngestor
from src.intelligence.sentiment_scorer import SentimentScorer

logger = logging.getLogger(__name__)


def load_intelligence_config() -> dict[str, Any]:
    path = CONFIG_DIR / "intelligence.yaml"
    if not path.exists():
        return {"intelligence": {"enabled": False}}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    intel = raw.get("intelligence", {})
    return {
        **intel,
        "event_impact_tiers": raw.get("event_impact_tiers", {}),
        "symbol_queries": raw.get("symbol_queries", {}),
        "currency_symbols": raw.get("currency_symbols", {}),
    }


class MarketIntelligenceService:
    """Central service for non-technical market context."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_intelligence_config()
        env_enabled = os.getenv("INTELLIGENCE_ENABLED", "").lower()
        if env_enabled in ("0", "false", "no"):
            self.config["enabled"] = False
        elif env_enabled in ("1", "true", "yes"):
            self.config["enabled"] = True

        self.calendar = CalendarMonitor(self.config)
        self.news = NewsIngestor(self.config)
        self.sentiment_scorer = SentimentScorer(self.config)
        self.macro = MacroOverlay(self.config)
        self.event_gate = EventRiskGate(self.calendar, self.config)
        self._sentiment: dict[str, SentimentSnapshot] = {}
        self._last_refresh_ok = False

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def refresh(self, symbols: list[str], force: bool = False) -> None:
        if not self.enabled:
            return
        try:
            self.calendar.refresh(force=force)
            self.macro.refresh(force=force)
            headlines = self.news.refresh(symbols, force=force)
            macro = self.macro.regime
            self._sentiment = {
                sym: self.sentiment_scorer.score(sym, headlines.get(sym, []), macro.bias)
                for sym in symbols
            }
            self._last_refresh_ok = True
            logger.info("Market intelligence refreshed for %d symbols", len(symbols))
        except Exception:
            logger.warning("Market intelligence refresh failed", exc_info=True)
            self._last_refresh_ok = False

    def get_sentiment(self, symbol: str) -> SentimentSnapshot | None:
        return self._sentiment.get(symbol)

    def get_macro(self) -> MacroRegime:
        return self.macro.regime

    def evaluate_event_gate(self, symbol: str) -> EventGateResult:
        if not self.enabled or os.getenv("EVENT_RISK_GATE_ENABLED", "true").lower() in ("0", "false"):
            return EventGateResult(allowed=True, reason="Intelligence disabled")
        return self.event_gate.evaluate(symbol)

    def upcoming_events(self, hours: int = 8) -> list[dict]:
        return [
            {
                "name": e.name,
                "currency": e.currency,
                "impact": e.impact,
                "scheduled_at": e.scheduled_at,
            }
            for e in self.calendar.upcoming(hours)
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "refresh_ok": self._last_refresh_ok,
            "macro": self.macro.regime.to_dict(),
            "upcoming_events": self.upcoming_events(),
            "sentiment": {sym: s.to_dict() for sym, s in self._sentiment.items()},
        }

    def persist_snapshot(self) -> None:
        cache_dir = Path(self.config.get("cache_dir", "data/intelligence"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        import json

        path = cache_dir / "latest_snapshot.json"
        path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
