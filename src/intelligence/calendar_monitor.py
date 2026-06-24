"""Economic calendar monitor — fetches and caches high-impact events."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.intelligence.jblanked_client import (
    fetch_jblanked_events,
    jblanked_api_key,
    jblanked_impact_tier,
    parse_jblanked_date,
)
from src.intelligence.models import CalendarEvent
from src.intelligence.rapidapi_client import (
    fetch_forex_factory_calendar_window,
    parse_forex_factory_event,
    rapidapi_key,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CalendarMonitor:
    """Tracks economic calendar events with tiered impact classification."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        cal_cfg = config.get("calendar", {})
        self.tier_windows = {
            1: int(cal_cfg.get("tier_1_window_minutes", 30)),
            2: int(cal_cfg.get("tier_2_window_minutes", 15)),
            3: 0,
        }
        self.impact_tiers = config.get("event_impact_tiers", {})
        self.currency_symbols: dict[str, list[str]] = config.get("currency_symbols", {})
        self.cache_dir = Path(config.get("cache_dir", "data/intelligence"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "calendar_cache.json"
        self._events: list[CalendarEvent] = []
        self._last_refresh: datetime | None = None
        self.live_mode = bool(config.get("live_mode", False))
        self.cache_max_age_hours = int(cal_cfg.get("cache_max_age_hours", 24))
        news_cfg = config.get("news", {})
        self.jblanked_source = news_cfg.get("jblanked_source", "mql5")
        self.jblanked_base = news_cfg.get(
            "jblanked_base_url", "https://www.jblanked.com/news/api"
        ).rstrip("/")
        self.rapidapi_days_ahead = int(cal_cfg.get("rapidapi_days_ahead", 1))

    def _rapidapi_forex_factory_events(self, now: datetime) -> list[CalendarEvent]:
        if not rapidapi_key():
            logger.warning("RapidAPI key missing — calendar fetch skipped")
            return []
        raw = fetch_forex_factory_calendar_window(days_ahead=self.rapidapi_days_ahead)
        events: list[CalendarEvent] = []
        for item in raw:
            parsed = parse_forex_factory_event(item)
            name = parsed["name"]
            tier = parsed["impact"]
            if tier == "tier_3":
                tier = self._classify_impact(name)
            events.append(
                CalendarEvent(
                    name=name,
                    currency=parsed["currency"],
                    impact=tier,
                    scheduled_at=parsed["scheduled_at"],
                    actual=parsed["actual"],
                    forecast=parsed["forecast"],
                    previous=parsed["previous"],
                ),
            )
        return events

    def _jblanked_calendar_events(self, now: datetime) -> list[CalendarEvent]:
        raw = fetch_jblanked_events(
            source=self.jblanked_source,
            mode="calendar",
            base_url=self.jblanked_base,
            api_key=jblanked_api_key(),
        )
        if raw is None:
            return []
        events: list[CalendarEvent] = []
        for item in raw:
            name = (item.get("Name") or "Economic event").strip()
            currency = (item.get("Currency") or "").strip().upper()
            scheduled = parse_jblanked_date(str(item.get("Date") or now.isoformat()))
            impact_label = (item.get("Impact") or "").strip()
            tier = jblanked_impact_tier(impact_label)
            if tier == "tier_3" and impact_label:
                tier = self._classify_impact(name)
            events.append(
                CalendarEvent(
                    name=name,
                    currency=currency,
                    impact=tier,
                    scheduled_at=scheduled,
                    actual=str(item.get("Actual") or ""),
                    forecast=str(item.get("Forecast") or ""),
                    previous=str(item.get("Previous") or ""),
                ),
            )
        return events

    def _classify_impact(self, name: str) -> str:
        name_lower = name.lower()
        for event in self.impact_tiers.get("tier_1", []):
            if event.lower() in name_lower:
                return "tier_1"
        for event in self.impact_tiers.get("tier_2", []):
            if event.lower() in name_lower:
                return "tier_2"
        return "tier_3"

    def _fixture_events(self, now: datetime) -> list[CalendarEvent]:
        """Deterministic demo events for simulation and offline use."""
        base = now.replace(hour=13, minute=30, second=0, microsecond=0)
        if base < now:
            base += timedelta(days=1)
        return [
            CalendarEvent(
                name="CPI",
                currency="USD",
                impact="tier_1",
                scheduled_at=base.isoformat(),
                forecast="0.3%",
                previous="0.2%",
            ),
            CalendarEvent(
                name="ECB Rate Decision",
                currency="EUR",
                impact="tier_1",
                scheduled_at=(base + timedelta(hours=2)).isoformat(),
            ),
            CalendarEvent(
                name="PMI",
                currency="USD",
                impact="tier_2",
                scheduled_at=(base + timedelta(hours=4)).isoformat(),
            ),
            CalendarEvent(
                name="Consumer Confidence",
                currency="USD",
                impact="tier_3",
                scheduled_at=(base + timedelta(hours=6)).isoformat(),
            ),
        ]

    def _load_cache(self) -> list[CalendarEvent]:
        if not self.cache_path.exists():
            return []
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return [CalendarEvent(**item) for item in raw.get("events", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _cache_is_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            refreshed_at = raw.get("refreshed_at")
            if not refreshed_at:
                return False
            refreshed = _parse_dt(refreshed_at)
            age_hours = (_utc_now() - refreshed).total_seconds() / 3600
            return age_hours <= self.cache_max_age_hours
        except (OSError, ValueError, TypeError):
            return False

    def _save_cache(self, events: list[CalendarEvent]) -> None:
        payload = {
            "refreshed_at": _utc_now().isoformat(),
            "events": [
                {
                    "name": e.name,
                    "currency": e.currency,
                    "impact": e.impact,
                    "scheduled_at": e.scheduled_at,
                    "actual": e.actual,
                    "forecast": e.forecast,
                    "previous": e.previous,
                }
                for e in events
            ],
        }
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def refresh(self, force: bool = False) -> list[CalendarEvent]:
        now = _utc_now()
        if (
            not force
            and self._last_refresh
            and (now - self._last_refresh).total_seconds() < 300
        ):
            return self._events

        source = self.config.get("calendar", {}).get("source", "fixture")
        if source == "cache" or (self.cache_path.exists() and self._cache_is_fresh() and source != "jblanked"):
            events = self._load_cache()
            if not events and not self.live_mode:
                events = self._fixture_events(now)
        elif source == "jblanked":
            events = self._jblanked_calendar_events(now)
            if not events and self.cache_path.exists():
                events = self._load_cache()
        elif source in ("rapidapi_forex_factory", "rapidapi"):
            events = self._rapidapi_forex_factory_events(now)
            if not events:
                logger.info("RapidAPI calendar empty — trying JBlanked fallback")
                events = self._jblanked_calendar_events(now)
            if not events and self.cache_path.exists():
                events = self._load_cache()
        elif source == "fixture" or not self.live_mode:
            events = self._fixture_events(now)
        else:
            events = self._load_cache()

        cutoff = now - timedelta(hours=2)
        horizon = now + timedelta(hours=24)
        self._events = [
            e for e in events
            if cutoff <= _parse_dt(e.scheduled_at) <= horizon
        ]
        self._save_cache(self._events)
        self._last_refresh = now
        logger.info("Calendar refreshed: %d events in window", len(self._events))
        return self._events

    def upcoming(self, hours: int = 8) -> list[CalendarEvent]:
        now = _utc_now()
        horizon = now + timedelta(hours=hours)
        return sorted(
            [e for e in self._events if now <= _parse_dt(e.scheduled_at) <= horizon],
            key=lambda e: e.scheduled_at,
        )

    def events_for_symbol(self, symbol: str, now: datetime | None = None) -> list[CalendarEvent]:
        now = now or _utc_now()
        affected: list[CalendarEvent] = []
        for event in self._events:
            currencies = [event.currency]
            symbols = set()
            for cur in currencies:
                symbols.update(self.currency_symbols.get(cur, []))
            if symbol in symbols or event.currency == "USD" and "/" in symbol:
                affected.append(event)
        return affected

    def nearest_event(self, symbol: str, now: datetime | None = None) -> CalendarEvent | None:
        now = now or _utc_now()
        events = self.events_for_symbol(symbol, now)
        if not events:
            return None
        return min(events, key=lambda e: abs((_parse_dt(e.scheduled_at) - now).total_seconds()))
