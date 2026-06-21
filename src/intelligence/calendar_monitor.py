"""Economic calendar monitor — fetches and caches high-impact events."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.intelligence.models import CalendarEvent

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
        if source == "cache":
            events = self._load_cache()
        else:
            events = self._fixture_events(now)

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
