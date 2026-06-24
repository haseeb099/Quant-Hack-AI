"""Live tick cache from ZeroMQ subscription or simulation."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NOTIFY_INTERVAL_SEC = 1.0


@dataclass
class TickSnapshot:
    symbol: str
    bid: float
    ask: float
    mid: float
    spread: float
    updated_at: datetime

    @property
    def tick_age_ms(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.updated_at).total_seconds() * 1000)


def _iter_tick_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse MT5 batch `{"ticks":[...]}` or legacy single-tick shape."""
    ticks = raw.get("ticks")
    if isinstance(ticks, list):
        return [t for t in ticks if isinstance(t, dict)]
    if raw.get("symbol"):
        return [raw]
    return []


class LiveFeed:
    """Background poller that caches latest ticks per symbol."""

    def __init__(
        self,
        connector: Any,
        symbols: list[str],
        feature_update_seconds: int = 60,
        simulation: bool = False,
    ) -> None:
        self.connector = connector
        self.symbols = list(symbols)
        self.feature_update_seconds = feature_update_seconds
        self.simulation = simulation
        self._ticks: dict[str, TickSnapshot] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._last_notify_at: float = 0.0
        self._started_at: float = 0.0
        self._zero_tick_warned: bool = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started_at = time.monotonic()
        self._zero_tick_warned = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="quantai-live-feed")
        self._thread.start()
        if self.simulation:
            now = datetime.now(timezone.utc)
            for symbol in self.symbols:
                base = 100.0 + (hash(symbol) % 50)
                self._store_tick(symbol, base, base + 0.02, now)

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        import random

        while self._running:
            if self.simulation:
                now = datetime.now(timezone.utc)
                for symbol in self.symbols:
                    base = 100.0 + (hash(symbol) % 50)
                    spread = 0.0002 * base
                    bid = base + random.uniform(-0.5, 0.5)
                    ask = bid + spread
                    self._store_tick(symbol, bid, ask, now)
                self._maybe_notify_ticks()
            else:
                raw = self.connector.poll_ticks()
                stored = False
                if raw:
                    now = datetime.now(timezone.utc)
                    for entry in _iter_tick_entries(raw):
                        symbol = str(entry.get("symbol", ""))
                        bid = float(entry.get("bid", 0))
                        ask = float(entry.get("ask", bid))
                        if symbol and bid > 0:
                            self._store_tick(symbol, bid, ask, now)
                            stored = True
                if not stored:
                    stored = self._mt5_tick_fallback()
                if stored:
                    self._maybe_notify_ticks()
                elif not self._zero_tick_warned and time.monotonic() - self._started_at > 30:
                    with self._lock:
                        has_ticks = bool(self._ticks)
                    if not has_ticks:
                        logger.warning(
                            "LiveFeed: zero ticks stored after 30s in live mode — check ZMQ bridge and symbol aliases",
                        )
                        self._zero_tick_warned = True
            time.sleep(max(0.2, self.feature_update_seconds / 10))

    def _aliases_for(self, symbol: str) -> set[str]:
        keys = {symbol, symbol.replace("/", "").upper()}
        compact = symbol.replace("/", "").upper()
        for configured in self.symbols:
            if configured.replace("/", "").upper() == compact:
                keys.add(configured)
        return keys

    def _mt5_tick_fallback(self) -> bool:
        """Use MT5 Python API when ZeroMQ SUB ticks are contended or unavailable."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return False
            import MetaTrader5 as mt5

            now = datetime.now(timezone.utc)
            stored = False
            for symbol in self.symbols:
                mt5_sym = symbol.replace("/", "").upper()
                mt5.symbol_select(mt5_sym, True)
                tick = mt5.symbol_info_tick(mt5_sym)
                if tick is not None and float(tick.bid) > 0:
                    ask = float(tick.ask) if float(tick.ask) > 0 else float(tick.bid)
                    self._store_tick(symbol, float(tick.bid), ask, now)
                    stored = True
            return stored
        except Exception:
            logger.debug("MT5 tick fallback failed", exc_info=True)
            return False

    def _store_tick(self, symbol: str, bid: float, ask: float, updated_at: datetime) -> None:
        mid = (bid + ask) / 2
        spread = ask - bid
        snap = TickSnapshot(symbol=symbol, bid=bid, ask=ask, mid=mid, spread=spread, updated_at=updated_at)
        with self._lock:
            for key in self._aliases_for(symbol):
                self._ticks[key] = snap

    def _build_notify_payload(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._lock:
            unique = {id(t): t for t in self._ticks.values()}
            instruments = {
                snap.symbol: {
                    "bid": snap.bid,
                    "ask": snap.ask,
                    "mid": snap.mid,
                    "tick_age_ms": snap.tick_age_ms,
                }
                for snap in unique.values()
            }
        return {
            "instruments": instruments,
            "last_tick_at": now.isoformat(),
            "last_tick_age_ms": self.youngest_tick_age_ms(),
        }

    def _maybe_notify_ticks(self) -> None:
        now_mono = time.monotonic()
        if now_mono - self._last_notify_at < NOTIFY_INTERVAL_SEC:
            return
        self._last_notify_at = now_mono
        payload = self._build_notify_payload()
        try:
            from src.web.state_publisher import notify_ticks, update_live_market

            update_live_market(payload)
            notify_ticks(payload)
        except Exception:
            logger.debug("Tick notify failed", exc_info=True)

    def get_tick(self, symbol: str) -> TickSnapshot | None:
        with self._lock:
            return self._ticks.get(symbol) or self._ticks.get(symbol.replace("/", "").upper())

    def youngest_tick_age_ms(self) -> float | None:
        with self._lock:
            unique = {id(t): t for t in self._ticks.values()}
            ages = [t.tick_age_ms for t in unique.values()]
        return min(ages) if ages else None

    def is_healthy(self, max_age_ms: float = 5000) -> bool:
        age = self.youngest_tick_age_ms()
        return age is not None and age <= max_age_ms
