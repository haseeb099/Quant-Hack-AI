"""Market data quality checks before entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class MarketHealthStatus:
    health: str
    message: str
    block_entries: bool = False


class MarketValidator:
    """Validate tick freshness and price consistency vs bar close."""

    def __init__(
        self,
        max_tick_age_ms: float = 10000,
        max_price_deviation_atr: float = 2.5,
        max_bar_age_sec: float = 1200,
    ) -> None:
        self.max_tick_age_ms = max_tick_age_ms
        self.max_price_deviation_atr = max_price_deviation_atr
        self.max_bar_age_sec = max_bar_age_sec
        self._last_bar_at: dict[str, datetime] = {}

    def record_bar_time(self, symbol: str, when: datetime | None = None) -> None:
        self._last_bar_at[symbol] = when or datetime.now(timezone.utc)

    def validate(
        self,
        symbol: str,
        tick_mid: float | None,
        bar_close: float,
        atr_14: float,
        tick_age_ms: float,
        require_tick: bool = False,
    ) -> MarketHealthStatus:
        if tick_mid is None:
            return MarketHealthStatus(
                health="red" if require_tick else "amber",
                message=f"No live tick for {symbol}",
                block_entries=require_tick,
            )

        if tick_age_ms > self.max_tick_age_ms:
            return MarketHealthStatus(
                health="red",
                message=f"Stale tick ({tick_age_ms:.0f}ms) for {symbol}",
                block_entries=True,
            )

        deviation = abs(tick_mid - bar_close)
        if atr_14 > 0 and deviation > atr_14 * self.max_price_deviation_atr:
            return MarketHealthStatus(
                health="red",
                message=f"Tick/bar divergence {deviation:.4f} > {self.max_price_deviation_atr}×ATR",
                block_entries=True,
            )

        last_bar = self._last_bar_at.get(symbol)
        if last_bar is not None:
            bar_age = (datetime.now(timezone.utc) - last_bar).total_seconds()
            if bar_age > self.max_bar_age_sec:
                return MarketHealthStatus(
                    health="amber",
                    message=f"Bar data age {bar_age:.0f}s for {symbol}",
                    block_entries=False,
                )

        return MarketHealthStatus(health="green", message="ok", block_entries=False)
