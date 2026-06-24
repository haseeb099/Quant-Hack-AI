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
from src.intelligence.rapidapi_client import rapidapi_key
from src.intelligence.sentiment_scorer import SentimentScorer

logger = logging.getLogger(__name__)


def _apply_intelligence_env_overrides(config: dict[str, Any], *, live_mode: bool = False) -> dict[str, Any]:
    """Apply documented .env overrides on top of intelligence.yaml."""
    news_source = os.getenv("NEWS_API_SOURCE", "").strip()
    if news_source:
        config.setdefault("news", {})["source"] = news_source
    elif live_mode and rapidapi_key() and os.getenv("RAPIDAPI_NEWS", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        config.setdefault("news", {})["source"] = "rapidapi_yahoo"
    elif live_mode and os.getenv("JBLANKED_API_KEY", "").strip():
        config.setdefault("news", {})["source"] = "jblanked"
    elif live_mode and os.getenv("NEWS_API_KEY", "").strip():
        config.setdefault("news", {})["source"] = "newsapi"

    jblanked_source = os.getenv("JBLANKED_NEWS_SOURCE", "").strip()
    if jblanked_source:
        config.setdefault("news", {})["jblanked_source"] = jblanked_source

    calendar_source = os.getenv("CALENDAR_SOURCE", "").strip()
    if calendar_source:
        config.setdefault("calendar", {})["source"] = calendar_source
    elif live_mode and rapidapi_key() and os.getenv("RAPIDAPI_CALENDAR", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        config.setdefault("calendar", {})["source"] = "rapidapi_forex_factory"
    elif live_mode and os.getenv("JBLANKED_API_KEY", "").strip():
        config.setdefault("calendar", {})["source"] = "jblanked"
    elif live_mode:
        cache_path = Path(config.get("cache_dir", "data/intelligence")) / "calendar_cache.json"
        if cache_path.exists():
            config.setdefault("calendar", {})["source"] = "cache"

    fear_greed = os.getenv("FEAR_GREED_ENABLED", "").strip().lower()
    if fear_greed in ("0", "false", "no"):
        config.setdefault("macro", {})["fear_greed_enabled"] = False
    elif fear_greed in ("1", "true", "yes"):
        config.setdefault("macro", {})["fear_greed_enabled"] = True

    refresh = os.getenv("INTELLIGENCE_REFRESH_MINUTES", "").strip()
    if refresh:
        config["refresh_minutes"] = int(refresh)

    budget = os.getenv("INTELLIGENCE_LLM_BUDGET_PER_CYCLE", "").strip()
    if budget:
        config["llm_budget_per_cycle_usd"] = float(budget)

    sent_cfg = config.setdefault("sentiment", {})
    if os.getenv("SENTIMENT_LLM_ENABLED", "").strip():
        from src.utils.llm_providers import sentiment_llm_enabled

        sent_cfg["llm_enabled"] = sentiment_llm_enabled(sent_cfg.get("llm_enabled", True))

    if os.getenv("SENTIMENT_LEXICON_FIRST", "").strip():
        from src.utils.llm_providers import sentiment_lexicon_first

        sent_cfg["lexicon_first"] = sentiment_lexicon_first()

    return config


def load_intelligence_config() -> dict[str, Any]:
    path = CONFIG_DIR / "intelligence.yaml"
    if not path.exists():
        return _apply_intelligence_env_overrides({"enabled": False}, live_mode=False)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    intel = raw.get("intelligence", {})
    config = {
        **intel,
        "event_impact_tiers": raw.get("event_impact_tiers", {}),
        "symbol_queries": raw.get("symbol_queries", {}),
        "currency_symbols": raw.get("currency_symbols", {}),
    }
    return _apply_intelligence_env_overrides(config, live_mode=False)


def load_intelligence_config_for_mode(*, live_mode: bool) -> dict[str, Any]:
    config = load_intelligence_config()
    return _apply_intelligence_env_overrides(config, live_mode=live_mode)


class MarketIntelligenceService:
    """Central service for non-technical market context."""

    def __init__(self, config: dict[str, Any] | None = None, live_mode: bool = False) -> None:
        if config is None:
            self.config = load_intelligence_config_for_mode(live_mode=live_mode)
        else:
            self.config = _apply_intelligence_env_overrides(dict(config), live_mode=live_mode)
        env_enabled = os.getenv("INTELLIGENCE_ENABLED", "").lower()
        if env_enabled in ("0", "false", "no"):
            self.config["enabled"] = False
        elif env_enabled in ("1", "true", "yes"):
            self.config["enabled"] = True

        self.config["live_mode"] = live_mode or bool(self.config.get("live_mode", False))

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
                sym: self.sentiment_scorer.score(
                    sym,
                    headlines.get(sym, []),
                    macro.bias,
                    usd_strength=macro.usd_strength,
                )
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
        intel_enabled = self.enabled
        return {
            "enabled": intel_enabled,
            "refresh_ok": True if not intel_enabled else self._last_refresh_ok,
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
