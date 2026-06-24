"""Tests for reconciler closed positions vs jsonl comparison."""

from __future__ import annotations

from src.operator.reconciler import reconcile_portfolio


def test_closed_positions_jsonl_passes_within_tolerance() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        closed_positions_24h=52,
        jsonl_closed_24h=50,
        exit_deals_24h=150,
        deals_24h=282,
    )
    issue = next(i for i in result["issues"] if i["code"] == "CLOSED_POSITIONS_JSONL")
    assert issue["passed"] is True
    assert "closed_positions=52" in issue["detail"]


def test_closed_positions_jsonl_fails_when_far_from_jsonl() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 100_000.0},
        engine_account={"equity": 100_000.0},
        closed_positions_24h=100,
        jsonl_closed_24h=10,
    )
    issue = next(i for i in result["issues"] if i["code"] == "CLOSED_POSITIONS_JSONL")
    assert issue["passed"] is False
