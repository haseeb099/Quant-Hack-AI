"""Pre-trade event risk gate — blocks or reduces size around high-impact events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.intelligence.calendar_monitor import CalendarMonitor, _parse_dt
from src.intelligence.models import EventGateResult

logger = logging.getLogger(__name__)


class EventRiskGate:
    """Evaluates whether new entries are allowed given upcoming calendar events."""

    def __init__(self, calendar: CalendarMonitor, config: dict[str, Any]) -> None:
        self.calendar = calendar
        self.config = config
        cal_cfg = config.get("calendar", {})
        self.tier_2_size_mult = float(cal_cfg.get("tier_2_size_multiplier", 0.5))
        self.tier_2_min_conf = float(cal_cfg.get("tier_2_min_confidence", 0.80))
        self.enabled = config.get("enabled", True)

    def evaluate(self, symbol: str, now: datetime | None = None) -> EventGateResult:
        if not self.enabled:
            return EventGateResult(allowed=True, reason="Event gate disabled")

        now = now or datetime.now(timezone.utc)
        events = self.calendar.events_for_symbol(symbol, now)
        if not events:
            return EventGateResult(allowed=True, reason="No upcoming events for symbol")

        for event in events:
            event_time = _parse_dt(event.scheduled_at)
            delta_min = abs((event_time - now).total_seconds()) / 60.0
            tier = event.tier
            window = self.calendar.tier_windows.get(tier, 0)

            if tier == 1 and delta_min <= window:
                logger.info(
                    "Event gate BLOCK %s: %s in %.0f min",
                    symbol, event.name, delta_min,
                )
                return EventGateResult(
                    allowed=False,
                    size_multiplier=0.0,
                    reason=f"Tier-1 event {event.name} within {window}min window",
                    blocking_event=event,
                )

            if tier == 2 and delta_min <= window:
                logger.info(
                    "Event gate REDUCE %s: %s in %.0f min",
                    symbol, event.name, delta_min,
                )
                return EventGateResult(
                    allowed=True,
                    size_multiplier=self.tier_2_size_mult,
                    min_confidence_override=self.tier_2_min_conf,
                    reason=f"Tier-2 event {event.name} — size reduced",
                    blocking_event=event,
                )

        return EventGateResult(allowed=True, reason="Outside event windows")
