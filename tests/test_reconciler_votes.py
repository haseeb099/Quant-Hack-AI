"""Tests for reconciler vote-missing detection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.operator.reconciler import count_jsonl_closed_without_votes, reconcile_portfolio


def test_count_jsonl_closed_without_votes(tmp_path) -> None:
    journal = tmp_path / "trades.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {"status": "closed", "timestamp": now, "agent_votes": []},
        {"status": "closed", "timestamp": now, "agent_votes": [{"agent": "trend_surfer"}]},
        {"status": "ok", "timestamp": now, "agent_votes": []},
    ]
    journal.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    assert count_jsonl_closed_without_votes(journal, hours=24) == 1


def test_reconciler_reports_votes_missing() -> None:
    result = reconcile_portfolio(
        mt5_positions=[],
        engine_positions=[],
        mt5_account={"equity": 1_000_000},
        engine_account={"equity": 1_000_000},
        jsonl_votes_missing_24h=5,
    )
    issue = next(i for i in result["issues"] if i["code"] == "VOTES_MISSING")
    assert issue["passed"] is False
    assert "missing_votes=5" in issue["detail"]
