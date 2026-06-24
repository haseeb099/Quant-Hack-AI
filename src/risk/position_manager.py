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
MAX_HOLD_M15_BARS = 24
PROFIT_LOCK_M15_BARS = 12
PROFIT_LOCK_MIN_R = 0.75
M15_BAR_SECONDS = 15 * 60


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
        m15_bars = cfg.get("time_stop_m15_bars")
        self.time_stop_bars = int(m15_bars if m15_bars is not None else cfg.get("time_stop_bars", TIME_STOP_BARS))
        self.time_stop_min_r = cfg.get("time_stop_min_r", TIME_STOP_MIN_R)
        self.partial_take_r = cfg.get("partial_take_r", PARTIAL_TAKE_R)
        self.partial_fraction = cfg.get("partial_fraction", PARTIAL_TAKE_FRACTION)
        self.trail_after_r = cfg.get("trail_after_r", TRAIL_AFTER_R)
        self.trail_atr_mult = cfg.get("trail_atr_mult", TRAIL_ATR_MULT)
        self.enable_partial_takes = cfg.get("enable_partial_takes", True)
        self.enable_trailing = cfg.get("enable_trailing", True)
        self.enable_breakeven = cfg.get("enable_breakeven", True)
        self.breakeven_r = cfg.get("breakeven_r", BREAKEVEN_R)
        self.regime_flip_enabled = bool(cfg.get("regime_flip_enabled", True))
        self.max_hold_m15_bars = int(cfg.get("max_hold_m15_bars", MAX_HOLD_M15_BARS))
        self.profit_lock_m15_bars = int(cfg.get("profit_lock_m15_bars", PROFIT_LOCK_M15_BARS))
        self.profit_lock_min_r = float(cfg.get("profit_lock_min_r", PROFIT_LOCK_MIN_R))
        self.adverse_stop_m15_bars = int(cfg.get("adverse_stop_m15_bars", 0))
        self.adverse_stop_r = float(cfg.get("adverse_stop_r", -0.40))
        self._state = PositionManagerState()

    @staticmethod
    def _entry_time_from_position(pos: dict[str, Any]) -> str:
        ts = int(pos.get("time", 0) or 0)
        if ts > 0:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _m15_bars_since_entry(entry_time: str, current_bar_ts: datetime | None) -> int | None:
        if not current_bar_ts:
            return None
        try:
            entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
        except ValueError:
            return None
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        if current_bar_ts.tzinfo is None:
            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)
        delta_sec = max((current_bar_ts - entry_dt).total_seconds(), 0.0)
        return int(delta_sec // M15_BAR_SECONDS)

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
        exit_prices: dict[str, float] | None = None,
        spreads_by_symbol: dict[str, float] | None = None,
        volume_mins: dict[str, float] | None = None,
        m15_bar_times: dict[str, datetime] | None = None,
    ) -> list[ExitAction]:
        actions: list[ExitAction] = []
        active_tickets = set()
        exit_prices = exit_prices or current_prices
        spreads_by_symbol = spreads_by_symbol or {}
        volume_mins = volume_mins or {}
        m15_bar_times = m15_bar_times or {}

        for pos in positions:
            ticket = int(pos.get("ticket", 0))
            if not ticket:
                continue
            active_tickets.add(ticket)

            meta = self._state.meta.get(ticket)
            if meta is None:
                entry_price = float(pos.get("price_open", 0) or 0)
                meta = PositionMeta(
                    ticket=ticket,
                    symbol=str(pos.get("symbol", "")),
                    direction=str(pos.get("type", "BUY")).upper(),
                    entry_price=entry_price,
                    sl=float(pos["sl"]) if pos.get("sl") else None,
                    volume=float(pos.get("volume", 0)),
                    entry_time=self._entry_time_from_position(pos),
                    regime=current_regimes.get(str(pos.get("symbol", "")), "unknown"),
                )
                self._state.meta[ticket] = meta

            if meta.entry_price <= 0:
                meta.entry_price = float(pos.get("price_open", 0) or 0)
            if meta.entry_price <= 0:
                logger.warning(
                    "Skip exit rules for ticket %d — entry price unknown",
                    ticket,
                )
                continue

            symbol = meta.symbol
            bar_ts = m15_bar_times.get(symbol)
            bars_from_m15 = self._m15_bars_since_entry(meta.entry_time, bar_ts)
            if bars_from_m15 is not None:
                meta.bars_held = bars_from_m15
            else:
                meta.bars_held += 1

            price = exit_prices.get(
                symbol,
                current_prices.get(symbol, float(pos.get("price_current", meta.entry_price))),
            )
            spread = spreads_by_symbol.get(symbol, 0.0)
            atr = atr_by_symbol.get(symbol, 0.0)
            sl_dist = abs(meta.entry_price - (meta.sl or meta.entry_price))
            if sl_dist <= 0:
                sl_dist = atr * 1.5 if atr > 0 else meta.entry_price * 0.01

            spread_cost_in_r = (spread / sl_dist) if sl_dist > 0 and spread > 0 else 0.0

            if meta.direction in ("BUY", "LONG"):
                r_multiple = (price - meta.entry_price) / sl_dist
            else:
                r_multiple = (meta.entry_price - price) / sl_dist

            new_regime = current_regimes.get(symbol, meta.regime)
            if self.regime_flip_enabled and self._regime_against(
                meta.direction, meta.regime, new_regime,
            ):
                actions.append(ExitAction("close", ticket, reason=f"Regime flip {meta.regime}->{new_regime}"))
                continue

            if meta.bars_held >= self.time_stop_bars and r_multiple < self.time_stop_min_r:
                actions.append(ExitAction(
                    "close", ticket,
                    reason=f"Time stop ({meta.bars_held} M15 bars, R={r_multiple:.2f})",
                ))
                continue

            if (
                self.adverse_stop_m15_bars > 0
                and meta.bars_held >= self.adverse_stop_m15_bars
                and r_multiple <= self.adverse_stop_r
            ):
                actions.append(ExitAction(
                    "close", ticket,
                    reason=(
                        f"Adverse stop ({meta.bars_held} M15 bars, R={r_multiple:.2f})"
                    ),
                ))
                continue

            if (
                meta.bars_held >= self.max_hold_m15_bars
                and r_multiple >= self.profit_lock_min_r
            ):
                actions.append(ExitAction(
                    "close", ticket,
                    reason=(
                        f"Max hold profit lock ({meta.bars_held} M15 bars, R={r_multiple:.2f})"
                    ),
                ))
                continue

            if (
                meta.bars_held >= self.profit_lock_m15_bars
                and r_multiple >= self.profit_lock_min_r
                and not meta.partial_taken
            ):
                actions.append(ExitAction(
                    "close", ticket,
                    reason=(
                        f"Profit lock ({meta.bars_held} M15 bars, R={r_multiple:.2f})"
                    ),
                ))
                continue

            if self.enable_partial_takes and not meta.partial_taken and r_multiple >= self.partial_take_r:
                partial_vol = round(meta.volume * self.partial_fraction, 2)
                volume_min = volume_mins.get(symbol, 0.01)
                if partial_vol >= volume_min and partial_vol > 0:
                    actions.append(ExitAction(
                        "partial_close", ticket, volume=partial_vol,
                        reason=f"Partial take at +{r_multiple:.1f}R",
                    ))
                elif partial_vol > 0 and partial_vol < volume_min:
                    logger.debug(
                        "Skip partial for ticket %d — %.4f lots below min %.4f",
                        ticket,
                        partial_vol,
                        volume_min,
                    )

            breakeven_threshold = self.breakeven_r + spread_cost_in_r
            if (
                self.enable_breakeven
                and not meta.breakeven_moved
                and r_multiple >= breakeven_threshold
                and meta.sl is not None
            ):
                if meta.direction in ("BUY", "LONG"):
                    new_sl = meta.entry_price + spread
                else:
                    new_sl = meta.entry_price - spread
                actions.append(ExitAction(
                    "modify_sl", ticket, new_sl=new_sl,
                    reason="Move SL to spread-buffered breakeven",
                ))
                meta.breakeven_moved = True
                meta.sl = new_sl

            if self.enable_trailing and r_multiple >= self.trail_after_r and atr > 0:
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

        for ticket in list(self._state.meta.keys()):
            if ticket not in active_tickets:
                self._state.meta.pop(ticket, None)

        return actions

    def get_meta(self, ticket: int) -> PositionMeta | None:
        return self._state.meta.get(int(ticket))

    def on_close(self, ticket: int) -> None:
        self.remove(ticket)

    def confirm_partial(self, ticket: int, closed_volume: float) -> None:
        meta = self._state.meta.get(int(ticket))
        if meta is None:
            return
        meta.partial_taken = True
        meta.volume = max(meta.volume - closed_volume, 0.0)

    def apply_runtime_config(self, config: dict[str, Any]) -> None:
        """Update exit rules without losing per-ticket meta."""
        m15_bars = config.get("time_stop_m15_bars")
        if m15_bars is not None:
            self.time_stop_bars = int(m15_bars)
        elif "time_stop_bars" in config:
            self.time_stop_bars = int(config["time_stop_bars"])
        self.time_stop_min_r = config.get("time_stop_min_r", self.time_stop_min_r)
        self.partial_take_r = config.get("partial_take_r", self.partial_take_r)
        self.partial_fraction = config.get("partial_fraction", self.partial_fraction)
        self.trail_after_r = config.get("trail_after_r", self.trail_after_r)
        self.trail_atr_mult = config.get("trail_atr_mult", self.trail_atr_mult)
        self.enable_partial_takes = config.get("enable_partial_takes", self.enable_partial_takes)
        self.enable_trailing = config.get("enable_trailing", self.enable_trailing)
        self.enable_breakeven = config.get("enable_breakeven", self.enable_breakeven)
        self.breakeven_r = config.get("breakeven_r", self.breakeven_r)
        if "regime_flip_enabled" in config:
            self.regime_flip_enabled = bool(config["regime_flip_enabled"])
        if "max_hold_m15_bars" in config:
            self.max_hold_m15_bars = int(config["max_hold_m15_bars"])
        if "profit_lock_m15_bars" in config:
            self.profit_lock_m15_bars = int(config["profit_lock_m15_bars"])
        if "profit_lock_min_r" in config:
            self.profit_lock_min_r = float(config["profit_lock_min_r"])
        if "adverse_stop_m15_bars" in config:
            self.adverse_stop_m15_bars = int(config["adverse_stop_m15_bars"])
        if "adverse_stop_r" in config:
            self.adverse_stop_r = float(config["adverse_stop_r"])

    @staticmethod
    def _regime_against(direction: str, entry_regime: str, current_regime: str) -> bool:
        if entry_regime == current_regime:
            return False
        trend_regimes = {"trending", "volatile"}
        calm_regimes = {"ranging", "calm"}
        is_long = direction in ("BUY", "LONG")
        if is_long and entry_regime in trend_regimes and current_regime in calm_regimes:
            return True
        if not is_long and entry_regime in trend_regimes and current_regime in calm_regimes:
            return True
        return False
