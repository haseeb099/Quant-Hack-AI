"""Between-round window detection for adaptation runs."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Daily adaptation window: 22:00–23:00 BST (competition round cutoffs)
_ADAPT_TZ = ZoneInfo("Europe/London")
_ADAPT_START = time(22, 0)
_ADAPT_END = time(23, 0)

# Competition round dates (inclusive start through end of adaptation window)
_COMPETITION_DAYS = {
    datetime(2026, 6, 21, tzinfo=_ADAPT_TZ).date(),
    datetime(2026, 6, 22, tzinfo=_ADAPT_TZ).date(),
    datetime(2026, 6, 23, tzinfo=_ADAPT_TZ).date(),
    datetime(2026, 6, 24, tzinfo=_ADAPT_TZ).date(),
}


def is_scheduled_adaptation_window(now: datetime | None = None) -> bool:
    """True during 22:00–23:00 BST on competition round transition days."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(_ADAPT_TZ)
    if local.date() not in _COMPETITION_DAYS:
        return False
    return _ADAPT_START <= local.time() < _ADAPT_END


def can_run_adaptation(state: dict[str, Any]) -> tuple[bool, str]:
    """Whether adaptation is safe to run from the dashboard."""
    mode = str(state.get("mode", "simulate"))
    engine_running = bool(state.get("engine_running"))
    engine_paused = bool(state.get("engine_paused"))
    cycle_active = bool(state.get("cycle_in_progress"))

    if cycle_active:
        return False, "Cycle in progress — wait for completion"

    if mode == "live" and engine_running and not engine_paused:
        return False, "Pause engine or wait for between-round window (22:00–23:00 BST)"

    if is_scheduled_adaptation_window():
        return True, "Between-round adaptation window open"

    if mode != "live":
        return True, "Simulate/demo mode — adaptation allowed"

    if engine_paused or not engine_running:
        return True, "Engine paused or stopped — adaptation allowed"

    return False, "Live trading active — pause engine before adaptation"


def adaptation_status(state: dict[str, Any]) -> dict[str, Any]:
    allowed, reason = can_run_adaptation(state)
    now = datetime.now(timezone.utc)
    local = now.astimezone(_ADAPT_TZ)
    return {
        "can_run": allowed,
        "reason": reason,
        "scheduled_window_open": is_scheduled_adaptation_window(now),
        "local_time_bst": local.isoformat(),
        "mode": state.get("mode", "simulate"),
        "engine_running": state.get("engine_running", False),
        "engine_paused": state.get("engine_paused", False),
    }
