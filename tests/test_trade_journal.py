"""Tests for trade journal recovery helpers."""

from __future__ import annotations

import json

from src.engine.trade_journal import closed_tickets_from_jsonl, context_from_jsonl, display_symbol
from src.utils.trade_logger import TradeLogger


def _write_jsonl(path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def test_closed_tickets_from_jsonl(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {"status": "ok", "ticket": 100},
            {"status": "closed", "ticket": 100, "extra": {"pnl": 10}},
            {"status": "closed", "extra": {"ticket": 200}},
            {"status": "error", "ticket": 300},
        ],
    )
    assert closed_tickets_from_jsonl(journal) == {100, 200}


def test_closed_tickets_missing_file(tmp_path) -> None:
    assert closed_tickets_from_jsonl(tmp_path / "missing.jsonl") == set()


def test_context_from_jsonl_uses_slippage_as_entry(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {
                "status": "decision",
                "ticket": 42818,
                "symbol": "AUD/USD",
                "direction": "Direction.BUY",
                "size": 5.73,
                "timestamp": "2026-06-22T10:00:00+00:00",
            },
            {
                "status": "ok",
                "ticket": 42818,
                "symbol": "AUD/USD",
                "direction": "Direction.BUY",
                "size": 5.73,
                "slippage": 0.65432,
                "agent_votes": [{"agent": "trend_surfer", "direction": "BUY"}],
                "session": "london",
                "regime": "trending",
                "reasoning": "Consensus entry",
            },
        ],
    )
    ctx = context_from_jsonl(42818, journal)
    assert ctx["symbol"] == "AUD/USD"
    assert ctx["direction"] == "BUY"
    assert ctx["entry_price"] == 0.65432
    assert ctx["volume"] == 5.73
    assert ctx["agent"] == "trend_surfer"
    assert ctx["session"] == "london"


def test_context_from_jsonl_no_match(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(journal, [{"status": "ok", "ticket": 1}])
    assert context_from_jsonl(999, journal) == {}


def test_context_from_jsonl_ignores_slippage_delta(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {
                "status": "ok",
                "ticket": 55,
                "symbol": "EUR/USD",
                "direction": "Direction.BUY",
                "size": 1.0,
                "slippage": 0.00012,
            },
        ],
    )
    ctx = context_from_jsonl(55, journal)
    assert ctx["entry_price"] == 0.0


def test_context_from_jsonl_prefers_richer_agent_votes(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {
                "status": "closed",
                "ticket": 900,
                "symbol": "XAU/USD",
                "direction": "SELL",
                "agent_votes": [],
                "extra": {"ticket": 900, "pnl": -50},
            },
            {
                "status": "ok",
                "ticket": 900,
                "symbol": "XAU/USD",
                "direction": "SELL",
                "agent_votes": [
                    {"agent": "trend_surfer", "direction": "SELL", "confidence": 0.82},
                    {"agent": "mean_reversion", "direction": "SELL", "confidence": 0.71},
                ],
            },
        ],
    )
    ctx = context_from_jsonl(900, journal)
    assert len(ctx["agent_votes"]) == 2
    assert ctx["agent"] == "trend_surfer"


def test_display_symbol_normalizes_mt5_key() -> None:
    assert display_symbol("EURGBP") == "EUR/GBP"
    assert display_symbol("EUR/GBP") == "EUR/GBP"


def test_trade_logger_normalizes_symbol(tmp_path) -> None:
    logger = TradeLogger(log_dir=tmp_path)
    logger.log(
        symbol="EURGBP",
        regime="trending",
        session="london",
        direction="SELL",
        confidence=0.7,
        status="decision",
    )
    line = (tmp_path / "trades.jsonl").read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["symbol"] == "EUR/GBP"
