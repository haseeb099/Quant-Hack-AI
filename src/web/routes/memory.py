"""Layered memory API — working, semantic, and similar setups."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.copilot.memory_context import MemoryContextBuilder

router = APIRouter(tags=["memory"])

_builder = MemoryContextBuilder()


@router.get("/api/memory/context")
def get_memory_context(
    symbol: str | None = Query(None, min_length=3),
) -> dict:
    """Grounded memory snapshot for dashboard cards and copilot."""
    return _builder.build(symbol=symbol.strip() if symbol else None)


@router.get("/api/memory/working")
def get_working_memory() -> dict:
    working = _builder.memory.get_working_memory()
    return {
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "session": t.session,
                "regime": t.regime,
                "agent": t.agent,
                "direction": t.direction,
                "r_multiple": t.r_multiple,
                "pnl": t.pnl,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
            }
            for t in working
        ],
        "count": len(working),
        "capacity": _builder.memory.WORKING_MEMORY_SIZE,
    }
