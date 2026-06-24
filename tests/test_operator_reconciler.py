"""Tests for portfolio reconciler."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.operator.reconciler import (
    aggregate_status,
    count_jsonl_closed_since,
    count_jsonl_partial_close_since,
    count_jsonl_unique_closed_tickets_since,
    reconcile_portfolio,
)


def test_reconcile_matching_positions_green() -> None:
    positions = [
        {"ticket": 101, "symbol": "EUR/USD", "volume": 0.1},
        {"ticket": 102, "symbol": "GBP/USD", "volume": 0.2},
    ]
    result = reconcile_portfolio(
        mt5_positions=positions,
        engine_positions=positions,
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        open_trades={101: {"symbol": "EUR/USD"}, 102: {"symbol": "GBP/USD"}},
    )
    assert result["status"] == "GREEN"
    assert result["summary"]["mt5_position_count"] == 2


def test_reconcile_unknown_mt5_position_red() -> None:
    mt5_positions = [{"ticket": 999, "symbol": "XAU/USD", "volume": 0.1}]
    engine_positions: list[dict] = []
    result = reconcile_portfolio(
        mt5_positions=mt5_positions,
        engine_positions=engine_positions,
        mt5_account={"equity": 50_000.0},
        engine_account={"equity": 50_000.0},
    )
    assert result["status"] == "RED"
    assert 999 in result["summary"]["unknown_mt5_tickets"]


def test_reconcile_orphan_open_trades_yellow() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 10_000.0},
        engine_account={"equity": 10_000.0},
        open_trades={42: {"symbol": "EUR/USD"}},
    )
    assert result["status"] == "YELLOW"
    assert 42 in result["summary"]["orphan_trades"]


def test_reconcile_equity_tolerance_warning() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 99_000.0},
        equity_tolerance_pct=0.5,
    )
    equity_issue = next(i for i in result["issues"] if i["code"] == "EQUITY")
    assert equity_issue["passed"] is False
    assert result["status"] == "YELLOW"


def test_aggregate_status_critical_beats_warning() -> None:
    issues = [
        {"passed": False, "severity": "WARNING"},
        {"passed": False, "severity": "CRITICAL"},
    ]
    assert aggregate_status(issues) == "RED"


def test_count_jsonl_closed_since_empty(tmp_path) -> None:
    path = tmp_path / "trades.jsonl"
    path.write_text("", encoding="utf-8")
    assert count_jsonl_closed_since(path, hours=24) == 0


def test_closed_positions_vs_jsonl_uses_position_count_not_exit_deals() -> None:
    """Exit deals inflate counts; closed positions should match jsonl within tolerance."""
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 10_000.0},
        engine_account={"equity": 10_000.0},
        closed_positions_24h=57,
        exit_deals_24h=150,
        jsonl_closed_24h=57,
        jsonl_partial_close_24h=12,
        mt5_partial_exit_deals_24h=93,
    )
    pos_issue = next(i for i in result["issues"] if i["code"] == "CLOSED_POSITIONS_JSONL")
    assert pos_issue["passed"] is True
    assert result["status"] == "GREEN"
    partial = next(i for i in result["issues"] if i["code"] == "PARTIAL_CLOSE_AUDIT")
    assert partial["passed"] is True


def test_memory_backfill_uses_jsonl_baseline_not_exit_deals() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 10_000.0},
        engine_account={"equity": 10_000.0},
        closed_positions_24h=57,
        exit_deals_24h=150,
        jsonl_closed_24h=57,
        jsonl_unique_closed_tickets_24h=57,
        memory_trade_count=54,
    )
    mem_issue = next(i for i in result["issues"] if i["code"] == "MEMORY_BACKFILL")
    assert mem_issue["passed"] is True
    assert "backlog≈3" in mem_issue["detail"]


def test_partial_close_jsonl_counter(tmp_path) -> None:
    path = tmp_path / "trades.jsonl"
    path.write_text(
        '{"status":"partial_close","timestamp":"2099-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    assert count_jsonl_partial_close_since(path, hours=24) == 1

def test_closed_positions_vs_jsonl_passes_with_small_delta() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        closed_positions_24h=57,
        jsonl_closed_24h=54,
    )
    issue = next(i for i in result["issues"] if i["code"] == "CLOSED_POSITIONS_JSONL")
    assert issue["passed"] is True


def test_exit_deals_inflate_count_but_closed_positions_match_jsonl() -> None:
    """150 exit deals vs 57 jsonl closes should pass when closed positions match."""
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        closed_positions_24h=57,
        jsonl_closed_24h=57,
        exit_deals_24h=150,
        deals_24h=200,
    )
    issue = next(i for i in result["issues"] if i["code"] == "CLOSED_POSITIONS_JSONL")
    assert issue["passed"] is True
    assert result["summary"]["exit_deals_24h"] == 150


def test_memory_backfill_uses_jsonl_unique_tickets_not_exit_deals() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        closed_positions_24h=150,
        jsonl_closed_24h=57,
        jsonl_unique_closed_tickets_24h=57,
        memory_trade_count=54,
        exit_deals_24h=150,
    )
    issue = next(i for i in result["issues"] if i["code"] == "MEMORY_BACKFILL")
    assert issue["passed"] is True
    assert "backlog≈3" in issue["detail"]


def test_partial_close_audit_is_informational(tmp_path) -> None:
    path = tmp_path / "trades.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"timestamp": now, "status": "partial_close", "symbol": "EUR/USD", "ticket": 1},
        {"timestamp": now, "status": "partial_close", "symbol": "EUR/USD", "ticket": 1},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert count_jsonl_partial_close_since(path, hours=24) == 2

    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        jsonl_partial_close_24h=2,
        mt5_partial_exit_deals_24h=8,
    )
    issue = next(i for i in result["issues"] if i["code"] == "PARTIAL_CLOSE_AUDIT")
    assert issue["passed"] is True
    assert issue["severity"] == "INFO"


def test_count_jsonl_unique_closed_tickets_dedupes(tmp_path) -> None:
    path = tmp_path / "trades.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"timestamp": now, "status": "closed", "ticket": 101, "symbol": "EUR/USD"},
        {"timestamp": now, "status": "closed", "ticket": 101, "symbol": "EUR/USD"},
        {"timestamp": now, "status": "closed", "ticket": 102, "symbol": "GBP/USD"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert count_jsonl_unique_closed_tickets_since(path, hours=24) == 2
    assert count_jsonl_closed_since(path, hours=24) == 3
