"""Tests for trade journal vote recovery."""

from __future__ import annotations

import json

from src.engine.trade_journal import context_from_jsonl


def _write_jsonl(path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def test_context_merges_richest_votes_from_earlier_line(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {
                "status": "decision",
                "ticket": 9001,
                "symbol": "XAU/USD",
                "direction": "SELL",
                "agent_votes": [
                    {"agent": "trend_surfer", "direction": "SELL", "confidence": 0.71},
                    {"agent": "mean_reversion", "direction": "SELL", "confidence": 0.68},
                ],
                "timestamp": "2026-06-22T10:00:00+00:00",
            },
            {
                "status": "closed",
                "ticket": 9001,
                "symbol": "XAU/USD",
                "direction": "SELL",
                "agent_votes": [],
                "extra": {"ticket": 9001, "pnl": -120.0},
                "timestamp": "2026-06-22T12:00:00+00:00",
            },
        ],
    )
    ctx = context_from_jsonl(9001, journal)
    assert len(ctx["agent_votes"]) == 2
    assert ctx["agent_votes"][0]["agent"] == "trend_surfer"
    assert ctx["symbol"] == "XAU/USD"


def test_context_prefers_ok_record_with_votes_over_empty_closed(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    _write_jsonl(
        journal,
        [
            {
                "status": "ok",
                "ticket": 7002,
                "symbol": "EUR/USD",
                "direction": "BUY",
                "slippage": 1.1025,
                "agent_votes": [{"agent": "breakout_hunter", "direction": "BUY"}],
                "session": "london",
                "regime": "trending",
            },
            {
                "status": "closed",
                "ticket": 7002,
                "symbol": "EUR/USD",
                "agent_votes": [],
            },
        ],
    )
    ctx = context_from_jsonl(7002, journal)
    assert ctx["entry_price"] == 1.1025
    assert ctx["agent"] == "breakout_hunter"
    assert len(ctx["agent_votes"]) == 1
