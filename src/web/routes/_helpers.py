"""Dashboard REST route helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

TRADES_PATH = Path("logs/trades.jsonl")
AGENT_NAMES = ["trend_surfer", "breakout_hunter", "momentum_pulse", "mean_reversion"]


def trade_id(record: dict[str, Any], line_index: int) -> str:
    raw = f"{record.get('timestamp', '')}|{record.get('symbol', '')}|{line_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def read_all_trades(path: Path | None = None) -> list[dict[str, Any]]:
    jsonl_path = path or TRADES_PATH
    if not jsonl_path.exists():
        return []
    trades: list[dict[str, Any]] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for idx, line in enumerate(f):
            try:
                record = json.loads(line)
                record["id"] = trade_id(record, idx)
                trades.append(record)
            except json.JSONDecodeError:
                continue
    return trades


def read_recent_trades(limit: int = 20, path: Path | None = None) -> list[dict[str, Any]]:
    return read_all_trades(path)[-limit:]


def agent_performance() -> list[dict[str, Any]]:
    try:
        from src.learning.layered_memory import LayeredMemory

        memory = LayeredMemory()
        return [
            {"agent": name, **memory.agent_performance(name)}
            for name in AGENT_NAMES
        ]
    except Exception:
        return []


def find_trade(trade_key: str, path: Path | None = None) -> dict[str, Any] | None:
    for record in read_all_trades(path):
        if record.get("id") == trade_key:
            return record
    return None
