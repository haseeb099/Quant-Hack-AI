"""Tests for live tick batch parsing and notify callback."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.data.live_feed import LiveFeed, _iter_tick_entries


class _TickConnector:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)

    def poll_ticks(self) -> dict | None:
        return self._payloads.pop(0) if self._payloads else None


def test_iter_tick_entries_batch_shape() -> None:
    raw = {
        "ticks": [
            {"symbol": "EURUSD", "bid": 1.08, "ask": 1.0802},
            {"symbol": "GBPUSD", "bid": 1.27, "ask": 1.2703},
        ],
    }
    entries = _iter_tick_entries(raw)
    assert len(entries) == 2
    assert entries[0]["symbol"] == "EURUSD"


def test_iter_tick_entries_legacy_single_tick() -> None:
    raw = {"symbol": "XAUUSD", "bid": 2350.0, "ask": 2350.5}
    entries = _iter_tick_entries(raw)
    assert len(entries) == 1
    assert entries[0]["symbol"] == "XAUUSD"


def test_live_feed_stores_batch_ticks_with_symbol_aliases() -> None:
    connector = _TickConnector([
        {"ticks": [{"symbol": "EURUSD", "bid": 1.08, "ask": 1.0802}]},
    ])
    feed = LiveFeed(connector, symbols=["EUR/USD"], simulation=False)
    now = datetime.now(timezone.utc)
    raw = {"ticks": [{"symbol": "EURUSD", "bid": 1.08, "ask": 1.0802}]}
    for entry in _iter_tick_entries(raw):
        symbol = str(entry.get("symbol", ""))
        bid = float(entry.get("bid", 0))
        ask = float(entry.get("ask", bid))
        if symbol and bid > 0:
            feed._store_tick(symbol, bid, ask, now)

    tick = feed.get_tick("EUR/USD")
    assert tick is not None
    assert tick.bid == 1.08
    assert tick.ask == 1.0802


def test_live_feed_notify_ticks_throttled() -> None:
    connector = _TickConnector([])
    feed = LiveFeed(connector, symbols=["EUR/USD"], simulation=True)
    notify = MagicMock()

    with patch("src.web.state_publisher.notify_ticks", notify), patch(
        "src.web.state_publisher.update_live_market",
    ):
        feed.start()
        feed._maybe_notify_ticks()
        feed._maybe_notify_ticks()
        feed.stop()

    assert notify.call_count == 1
    payload = notify.call_args[0][0]
    assert "instruments" in payload
    assert "last_tick_at" in payload
    assert "last_tick_age_ms" in payload
