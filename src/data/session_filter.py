"""UTC trading session windows and symbol/agent preferences."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SessionInfo:
    name: str
    preferred_instruments: tuple[str, ...]
    preferred_agents: tuple[str, ...]


# Competition crypto — trade 24/7 including UTC "closed" hours (21–23).
_CRYPTO_SYMBOLS: frozenset[str] = frozenset({
    "BAR/USD", "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
})

_DEFAULT_SESSIONS: dict[str, dict[str, Any]] = {
    "asia": {
        "start_hour": 0,
        "end_hour": 8,
        "preferred_instruments": ["USD/JPY", "AUD/USD", "XAU/USD"],
        "preferred_agents": ["mean_reversion", "trend_surfer"],
    },
    "london": {
        "start_hour": 8,
        "end_hour": 13,
        "preferred_instruments": ["EUR/USD", "GBP/USD", "XAU/USD"],
        "preferred_agents": ["breakout_hunter", "trend_surfer"],
    },
    "ny": {
        "start_hour": 13,
        "end_hour": 21,
        "preferred_instruments": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "preferred_agents": ["breakout_hunter", "momentum_pulse"],
    },
    "overlap": {
        "start_hour": 13,
        "end_hour": 16,
        "preferred_instruments": [],
        "preferred_agents": ["breakout_hunter", "momentum_pulse"],
    },
}


class SessionFilter:
    """Gate symbols and agents by UTC session windows."""

    def __init__(
        self,
        sessions: dict[str, Any] | None = None,
        symbol_filter_enabled: bool = True,
    ) -> None:
        self.sessions = sessions or _DEFAULT_SESSIONS
        self.symbol_filter_enabled = symbol_filter_enabled

    def _hour(self, ts: datetime | None = None) -> int:
        when = ts or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.hour

    def is_overlap(self, ts: datetime | None = None) -> bool:
        hour = self._hour(ts)
        overlap = self.sessions.get("overlap", {})
        return int(overlap.get("start_hour", 13)) <= hour < int(overlap.get("end_hour", 16))

    def session_name(self, ts: datetime | None = None) -> str:
        if self.is_overlap(ts):
            return "overlap"
        hour = self._hour(ts)
        if 0 <= hour < 8:
            return "asia"
        if 8 <= hour < 13:
            return "london"
        if 13 <= hour < 21:
            return "ny"
        return "closed"

    def current_session(self, ts: datetime | None = None) -> SessionInfo:
        name = self.session_name(ts)
        cfg = self.sessions.get(name, {})
        return SessionInfo(
            name=name,
            preferred_instruments=tuple(cfg.get("preferred_instruments", [])),
            preferred_agents=tuple(cfg.get("preferred_agents", [])),
        )

    def preferred_agents(self, ts: datetime | None = None) -> list[str]:
        return list(self.current_session(ts).preferred_agents)

    def is_symbol_preferred(self, symbol: str, ts: datetime | None = None) -> bool:
        if self.is_overlap(ts):
            return True
        preferred = self.current_session(ts).preferred_instruments
        return symbol in preferred

    def should_skip_symbol(self, symbol: str, ts: datetime | None = None) -> bool:
        if not self.symbol_filter_enabled:
            return False
        if self.is_overlap(ts):
            return False
        if symbol in _CRYPTO_SYMBOLS:
            return False
        return not self.is_symbol_preferred(symbol, ts)

    def should_trade_symbol(self, symbol: str, ts: datetime | None = None) -> bool:
        return not self.should_skip_symbol(symbol, ts)
