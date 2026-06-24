"""Open positions endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.risk.account_profile import position_notional_from_dict
from src.web.runtime_state import read_state

router = APIRouter(tags=["positions"])


@router.get("/api/positions")
def get_positions() -> dict:
    state = read_state()
    positions = state.get("positions", [])
    monitor = state.get("position_monitor", [])
    monitor_by_ticket = {
        int(m["ticket"]): m for m in monitor if m.get("ticket") is not None
    }
    enriched = []
    for p in positions:
        row = dict(p)
        ticket = p.get("ticket")
        if ticket is not None and int(ticket) in monitor_by_ticket:
            row["monitor"] = monitor_by_ticket[int(ticket)]
        enriched.append(row)
    total_exposure = 0.0
    total_pnl = 0.0
    for p in positions:
        notional_raw = p.get("notional")
        if notional_raw is not None:
            total_exposure += abs(float(notional_raw))
        else:
            contract = float(p.get("contract_size", 1))
            total_exposure += position_notional_from_dict(p, contract)
        total_pnl += float(p.get("profit", p.get("unrealized_pnl", 0)))
    return {
        "positions": enriched,
        "count": len(enriched),
        "total_exposure": total_exposure,
        "total_unrealized_pnl": total_pnl,
        "position_monitor": monitor,
    }
