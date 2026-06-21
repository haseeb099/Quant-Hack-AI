"""Live tick cache from ZeroMQ subscription or simulation."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


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

    def start(self) -> None:
        if self._running:
            return
        self._running = True
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
            else:
                raw = self.connector.poll_ticks()
                if raw:
                    symbol = str(raw.get("symbol", ""))
                    bid = float(raw.get("bid", 0))
                    ask = float(raw.get("ask", bid))
                    if symbol and bid > 0:
                        self._store_tick(symbol, bid, ask, datetime.now(timezone.utc))
            time.sleep(max(0.2, self.feature_update_seconds / 10))

    def _store_tick(self, symbol: str, bid: float, ask: float, updated_at: datetime) -> None:
        mid = (bid + ask) / 2
        spread = ask - bid
        snap = TickSnapshot(symbol=symbol, bid=bid, ask=ask, mid=mid, spread=spread, updated_at=updated_at)
        with self._lock:
            self._ticks[symbol] = snap
            self._ticks[symbol.replace("/", "").upper()] = snap

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
