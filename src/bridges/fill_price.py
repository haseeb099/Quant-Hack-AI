"""Resolve executable fill price after open — never treat slippage as price."""

from __future__ import annotations

from typing import Any


def _price_open_for_ticket(ticket: int, connector: Any) -> float:
    for pos in connector.get_positions():
        if int(pos.get("ticket", 0)) == int(ticket):
            return float(pos.get("price_open", 0) or 0)
    mt5_vol = getattr(connector, "_mt5_volume_for_ticket", None)
    positions_from_mt5 = getattr(connector, "_positions_from_mt5", None)
    if mt5_vol is not None and positions_from_mt5 is not None:
        positions = positions_from_mt5()
        if positions:
            for pos in positions:
                if int(pos.get("ticket", 0)) == int(ticket):
                    return float(pos.get("price_open", 0) or 0)
    return 0.0


def resolve_fill_price(
    result: dict[str, Any],
    ticket: int | None,
    symbol: str,
    fallback_price: float,
    connector: Any,
) -> float:
    """Priority: result price > MT5 price_open > fallback executable price."""
    price = float(result.get("price") or 0)
    if price > 0:
        return price

    if ticket:
        po = _price_open_for_ticket(int(ticket), connector)
        if po > 0:
            return po

    if fallback_price > 0:
        return float(fallback_price)
    return 0.0
