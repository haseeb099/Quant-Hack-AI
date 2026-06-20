"""Trade journal endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["trades"])

JSONL_PATH = Path("logs/trades.jsonl")


def _load_trades() -> list[dict[str, Any]]:
    if not JSONL_PATH.exists():
        return []
    trades: list[dict[str, Any]] = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                record = json.loads(line)
                record["id"] = str(i)
                trades.append(record)
            except json.JSONDecodeError:
                continue
    return trades


@router.get("/api/trades")
def list_trades(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    symbol: str | None = None,
    status: str | None = None,
) -> dict:
    trades = _load_trades()
    if symbol:
        trades = [t for t in trades if t.get("symbol") == symbol]
    if status:
        trades = [t for t in trades if t.get("status") == status]
    total = len(trades)
    page = list(reversed(trades))[offset: offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "trades": page}


@router.get("/api/trades/{trade_id}")
def get_trade(trade_id: str) -> dict:
    trades = _load_trades()
    try:
        idx = int(trade_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Trade not found") from exc
    if idx < 0 or idx >= len(trades):
        raise HTTPException(status_code=404, detail="Trade not found")
    record = trades[idx]
    record["id"] = str(idx)
    return record
