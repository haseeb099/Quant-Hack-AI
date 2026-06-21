"""Position exit management — trailing, time stops, partial takes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

TIME_STOP_BARS = 4
TIME_STOP_MIN_R = 0.5
PARTIAL_TAKE_R = 1.0
PARTIAL_TAKE_FRACTION = 0.5
TRAIL_AFTER_R = 2.0
TRAIL_ATR_MULT = 1.5
BREAKEVEN_R = 1.0


@dataclass
class PositionMeta:
    ticket: int
    symbol: str
    direction: str
    entry_price: float
    sl: float | None
    volume: float
    entry_time: str
    regime: str
    bars_held: int = 0
    partial_taken: bool = False
    breakeven_moved: bool = False


@dataclass
class ExitAction:
    action: str  # close, partial_close, modify_sl
    ticket: int
    volume: float | None = None
    new_sl: float | None = None
    reason: str = ""


@dataclass
class PositionManagerState:
    meta: dict[int, PositionMeta] = field(default_factory=dict)


class PositionManager:
    """Professional exit rules applied each decision cycle."""

    def __init__(self, config: dict[str, Any] | str | None = None) -> None:
        if isinstance(config, str):
            cfg: dict[str, Any] = {"phase": config}
        else:
            cfg = config or {}
        self.time_stop_bars = cfg.get("time_stop_bars", TIME_STOP_BARS)
        self.time_stop_min_r = cfg.get("time_stop_min_r", TIME_STOP_MIN_R)
        self.partial_take_r = cfg.get("partial_take_r", PARTIAL_TAKE_R)
        self.partial_fraction = cfg.get("partial_fraction", PARTIAL_TAKE_FRACTION)
        self.trail_after_r = cfg.get("trail_after_r", TRAIL_AFTER_R)
        self.trail_atr_mult = cfg.get("trail_atr_mult", TRAIL_ATR_MULT)
        self._state = PositionManagerState()

    def register_entry(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        sl: float | None,
        volume: float,
        regime: str,
    ) -> None:
        self._state.meta[ticket] = PositionMeta(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl=sl,
            volume=volume,
            entry_time=datetime.now(timezone.utc).isoformat(),
            regime=regime,
        )

    def remove(self, ticket: int) -> None:
        self._state.meta.pop(ticket, None)

    def evaluate(
        self,
        positions: list[dict[str, Any]],
        current_regimes: dict[str, str],
        atr_by_symbol: dict[str, float],
        current_prices: dict[str, float],
    ) -> list[ExitAction]:
        actions: list[ExitAction] = []
        active_tickets = set()

        for pos in positions:
            ticket = int(pos.get("ticket", 0))
            if not ticket:
                continue
            active_tickets.add(ticket)

            meta = self._state.meta.get(ticket)
            if meta is None:
                meta = PositionMeta(
                    ticket=ticket,
                    symbol=str(pos.get("symbol", "")),
                    direction=str(pos.get("type", "BUY")).upper(),
                    entry_price=float(pos.get("price_open", 0)),
                    sl=float(pos["sl"]) if pos.get("sl") else None,
                    volume=float(pos.get("volume", 0)),
                    entry_time=datetime.now(timezone.utc).isoformat(),
                    regime=current_regimes.get(str(pos.get("symbol", "")), "unknown"),
                )
                self._state.meta[ticket] = meta

            meta.bars_held += 1
            symbol = meta.symbol
            price = current_prices.get(symbol, float(pos.get("price_current", meta.entry_price)))
            atr = atr_by_symbol.get(symbol, 0.0)
            sl_dist = abs(meta.entry_price - (meta.sl or meta.entry_price))
            if sl_dist <= 0:
                sl_dist = atr * 1.5 if atr > 0 else meta.entry_price * 0.01

            if meta.direction in ("BUY", "LONG"):
                r_multiple = (price - meta.entry_price) / sl_dist
            else:
                r_multiple = (meta.entry_price - price) / sl_dist

            # Regime flip exit
            new_regime = current_regimes.get(symbol, meta.regime)
            if self._regime_against(meta.direction, meta.regime, new_regime):
                actions.append(ExitAction("close", ticket, reason=f"Regime flip {meta.regime}->{new_regime}"))
                continue

            # Time stop — no +0.5R in 4 bars
            if meta.bars_held >= self.time_stop_bars and r_multiple < self.time_stop_min_r:
                actions.append(ExitAction("close", ticket, reason=f"Time stop ({meta.bars_held} bars, R={r_multiple:.2f})"))
                continue

            # Partial take at +1R
            if not meta.partial_taken and r_multiple >= self.partial_take_r:
                partial_vol = round(meta.volume * self.partial_fraction, 2)
                if partial_vol > 0:
                    actions.append(ExitAction(
                        "partial_close", ticket, volume=partial_vol,
                        reason=f"Partial take at +{r_multiple:.1f}R",
                    ))
                    meta.partial_taken = True
                    meta.volume -= partial_vol

            # Breakeven at +1R
            if not meta.breakeven_moved and r_multiple >= BREAKEVEN_R and meta.sl is not None:
                actions.append(ExitAction("modify_sl", ticket, new_sl=meta.entry_price, reason="Move SL to breakeven"))
                meta.breakeven_moved = True
                meta.sl = meta.entry_price

            # Trailing stop after +2R
            if r_multiple >= self.trail_after_r and atr > 0:
                if meta.direction in ("BUY", "LONG"):
                    trail_sl = price - atr * self.trail_atr_mult
                    if meta.sl is None or trail_sl > meta.sl:
                        actions.append(ExitAction("modify_sl", ticket, new_sl=trail_sl, reason="Trail stop"))
                        meta.sl = trail_sl
                else:
                    trail_sl = price + atr * self.trail_atr_mult
                    if meta.sl is None or trail_sl < meta.sl:
                        actions.append(ExitAction("modify_sl", ticket, new_sl=trail_sl, reason="Trail stop"))
                        meta.sl = trail_sl

        # Clean closed positions
        for ticket in list(self._state.meta.keys()):
            if ticket not in active_tickets:
                self._state.meta.pop(ticket, None)

        return actions

    def on_close(self, ticket: int) -> None:
        self.remove(ticket)

    @staticmethod
    def _regime_against(direction: str, entry_regime: str, current_regime: str) -> bool:
        if entry_regime == current_regime:
            return False
        long_regimes = {"trending", "volatile"}
        short_regimes = {"ranging", "calm"}
        is_long = direction in ("BUY", "LONG")
        if is_long and entry_regime in long_regimes and current_regime in short_regimes:
            return True
        if not is_long and entry_regime in short_regimes and current_regime in long_regimes:
            return True
        return False
