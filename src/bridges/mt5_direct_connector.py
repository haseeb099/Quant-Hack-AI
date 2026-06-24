"""Direct MetaTrader5 Python API connector — fallback when ZeroMQ bridge is offline."""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any

import pandas as pd

from src.bridges.zeromq_connector import OHLCV_BAR_COUNT, account_equity
from src.integrations.mt5_session import ensure_mt5_session

logger = logging.getLogger(__name__)

MAGIC = 20260621
DEVIATION = 10
TRADE_MAX_RETRIES = 3

COMPETITION_SYMBOLS = [
    "AUDUSD", "EURCHF", "EURGBP", "EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY",
    "XAGUSD", "XAUUSD", "BARUSD", "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD",
]

_TIMEFRAME_MAP = {
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def _mt5_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def _terminal_allows_trading(term: Any | None) -> bool:
    if term is None:
        return False
    if not bool(getattr(term, "trade_allowed", False)):
        return False
    if bool(getattr(term, "tradeapi_disabled", True)):
        return False
    return True


def _account_trade_allowed(acc: Any, term: Any | None = None) -> bool:
    """Account + terminal must allow execution (Python API / Algo Trading)."""
    if acc is None:
        return False
    if not bool(getattr(acc, "trade_allowed", False)):
        return False
    if hasattr(acc, "trade_expert") and not bool(getattr(acc, "trade_expert", True)):
        return False
    return _terminal_allows_trading(term)


class Mt5DirectConnector:
    """Live trading via MetaTrader5 Python package (no ZeroMQ EA required)."""

    bridge_type = "direct"

    def __init__(self) -> None:
        self._connected = False
        self._trade_disabled = False
        self._last_error = ""
        self._io_lock = threading.RLock()
        self._mt5: Any = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def bridge_responding(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> str:
        return self._last_error

    def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            self._last_error = "MetaTrader5 package not installed"
            return False

        ok, detail = ensure_mt5_session(require_login=True)
        if not ok:
            self._last_error = detail
            self._connected = False
            return False

        acc = mt5.account_info()
        term = mt5.terminal_info()
        if acc is None:
            self._last_error = "MT5 account_info() returned None"
            self._connected = False
            return False

        trade_ok = _account_trade_allowed(acc, term)

        self._mt5 = mt5
        self._connected = True
        self._trade_disabled = not trade_ok
        self._last_error = ""
        if self._trade_disabled:
            self._last_error = (
                "Algorithmic trading disabled in MT5 — click Algo Trading (green) "
                "and allow Python API in Tools → Options → Expert Advisors"
            )
            logger.warning(self._last_error)
        else:
            logger.info(
                "MT5 direct API connected — login=%s equity=%.2f",
                getattr(acc, "login", "?"),
                float(getattr(acc, "equity", 0)),
            )
        return True

    def reconnect(self) -> bool:
        self.close()
        return self.connect()

    def refresh_health(self) -> bool:
        if not self._connected:
            return self.connect()
        acc = self._mt5.account_info()
        if acc is None:
            self._connected = False
            self._last_error = "MT5 session lost"
            return False
        term = self._mt5.terminal_info()
        self._trade_disabled = not _account_trade_allowed(acc, term)
        return True

    def health_check(self) -> tuple[bool, str]:
        if not self._connected:
            return False, self._last_error or "not connected"
        acc = self._mt5.account_info()
        if acc is None:
            return False, "account_info unavailable"
        return True, "ok"

    def get_account_info(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "error", "message": "MT5 not connected", "action": "ACCOUNT"}

        acc = self._mt5.account_info()
        if acc is None:
            return {"status": "error", "message": self._mt5.last_error(), "action": "ACCOUNT"}

        equity = float(acc.equity)
        gross_exposure = 0.0
        largest_pct = 0.0
        positions = self._mt5.positions_get() or []
        for pos in positions:
            contract = self._mt5.symbol_info(pos.symbol)
            contract_size = float(getattr(contract, "trade_contract_size", 1) or 1)
            pos_value = float(pos.volume) * contract_size * float(pos.price_open)
            gross_exposure += pos_value
            if equity > 0:
                largest_pct = max(largest_pct, pos_value / equity)

        margin = float(acc.margin)
        margin_level = (equity / margin * 100.0) if margin > 0 else 9999.0
        term = self._mt5.terminal_info()
        trade_allowed = _account_trade_allowed(acc, term)

        return {
            "status": "ok",
            "action": "ACCOUNT",
            "equity": equity,
            "balance": float(acc.balance),
            "margin": margin,
            "free_margin": float(acc.margin_free),
            "gross_exposure": gross_exposure,
            "largest_position_pct": largest_pct,
            "margin_level": margin_level,
            "trade_allowed": trade_allowed,
            "latency_ms": 0,
        }

    def get_symbol_info(self, symbol: str) -> dict[str, float] | None:
        if not self._connected:
            return None
        info = self._mt5.symbol_info(_mt5_symbol(symbol))
        if info is None:
            return None
        return {
            "contract_size": float(info.trade_contract_size or 1),
            "volume_min": float(info.volume_min or 0.01),
            "volume_step": float(info.volume_step or 0.01),
            "volume_max": float(info.volume_max or 100),
            "digits": float(info.digits or 5),
            "point": float(info.point or 0.0001),
            "stops_level": float(info.trade_stops_level or 0),
        }

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "M15",
        count: int = OHLCV_BAR_COUNT,
    ) -> pd.DataFrame | None:
        if not self._connected:
            return None
        mt5 = self._mt5
        tf_name = _TIMEFRAME_MAP.get(timeframe, "TIMEFRAME_M15")
        tf = getattr(mt5, tf_name, mt5.TIMEFRAME_M15)
        mt5.symbol_select(_mt5_symbol(symbol), True)
        rates = mt5.copy_rates_from_pos(_mt5_symbol(symbol), tf, 0, count)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df = df.rename(columns={"time": "timestamp", "tick_volume": "volume"})
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        positions = self._mt5.positions_get() or []
        out: list[dict[str, Any]] = []
        for pos in positions:
            contract = self._mt5.symbol_info(pos.symbol)
            contract_size = float(getattr(contract, "trade_contract_size", 1) or 1)
            notional = float(pos.volume) * contract_size * float(pos.price_open)
            out.append({
                "ticket": int(pos.ticket),
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == self._mt5.ORDER_TYPE_BUY else "SELL",
                "volume": float(pos.volume),
                "price_open": float(pos.price_open),
                "contract_size": contract_size,
                "notional": notional,
                "sl": float(pos.sl),
                "tp": float(pos.tp),
                "profit": float(pos.profit),
            })
        return out

    def poll_ticks(self) -> dict[str, Any] | None:
        if not self._connected:
            return None
        ticks: list[dict[str, Any]] = []
        for sym in COMPETITION_SYMBOLS:
            self._mt5.symbol_select(sym, True)
            tick = self._mt5.symbol_info_tick(sym)
            if tick is None or tick.bid <= 0:
                continue
            ticks.append({"symbol": sym, "bid": float(tick.bid), "ask": float(tick.ask)})
        if not ticks:
            return None
        return {"ticks": ticks}

    @staticmethod
    def _normalize_volume(volume: float, specs: dict[str, float] | None) -> float:
        if not specs or volume <= 0:
            return volume
        step = specs.get("volume_step", 0.01)
        vmin = specs.get("volume_min", 0.01)
        vmax = specs.get("volume_max", 100.0)
        if step > 0:
            volume = math.floor(volume / step) * step
        volume = max(vmin, min(volume, vmax))
        return round(volume, 8)

    def _order_send(self, request: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        last = None
        for attempt in range(TRADE_MAX_RETRIES):
            result = self._mt5.order_send(request)
            last = result
            if result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE:
                latency_ms = int((time.perf_counter() - start) * 1000)
                return {
                    "status": "ok",
                    "ticket": int(result.order or result.deal or 0),
                    "price": float(result.price or 0),
                    "slippage": 0.0,
                    "fill_rate": 1.0,
                    "latency_ms": latency_ms,
                    "retries": attempt,
                }
            if result is not None:
                retcode = result.retcode
                if retcode in (
                    self._mt5.TRADE_RETCODE_REQUOTE,
                    self._mt5.TRADE_RETCODE_PRICE_CHANGED,
                    self._mt5.TRADE_RETCODE_INVALID_PRICE,
                ):
                    time.sleep(0.2 * (attempt + 1))
                    continue
            break

        message = "order_send failed"
        if last is not None:
            message = f"{last.retcode}: {last.comment}"
        return {"status": "error", "message": message, "latency_ms": 0}

    def send_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        ticket: int | None = None,
        entry_mode: str = "market",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        if not self._connected:
            return {"status": "simulated", "symbol": symbol, "direction": direction, "volume": volume}

        term = self._mt5.terminal_info()
        acc = self._mt5.account_info()
        self._trade_disabled = not _account_trade_allowed(acc, term)
        if self._trade_disabled:
            if term is not None and not bool(getattr(term, "trade_allowed", False)):
                msg = "Enable Algo Trading in MT5 toolbar (button must be green)"
            elif term is not None and bool(getattr(term, "tradeapi_disabled", True)):
                msg = "Enable algorithmic trading via Python API in MT5 Expert Advisors settings"
            else:
                msg = "Algorithmic trading disabled in MT5"
            return {"status": "error", "message": msg}

        mt5 = self._mt5
        mt5_symbol = _mt5_symbol(symbol)
        mt5.symbol_select(mt5_symbol, True)
        specs = self.get_symbol_info(symbol)
        volume = self._normalize_volume(volume, specs)
        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            return {"status": "error", "message": f"No tick for {symbol}"}

        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if direction == "BUY" else tick.bid)
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": DEVIATION,
            "magic": MAGIC,
            "comment": "QuantAI",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None and sl > 0:
            request["sl"] = sl
        if tp is not None and tp > 0:
            request["tp"] = tp
        if ticket is not None:
            request["position"] = ticket

        with self._io_lock:
            result = self._order_send(request)
        if result.get("status") == "ok":
            result.update({"action": "TRADE", "symbol": symbol, "type": direction, "volume": volume})
            pos_ticket = self._resolve_position_ticket(mt5_symbol, result.get("ticket", 0))
            if pos_ticket:
                result["ticket"] = pos_ticket
        return result

    def _resolve_position_ticket(self, mt5_symbol: str, order_ticket: int) -> int:
        positions = self._mt5.positions_get(symbol=mt5_symbol) or []
        if not positions:
            return order_ticket
        latest = max(positions, key=lambda p: p.time)
        return int(latest.ticket)

    def close_position(self, ticket: int, volume: float | None = None) -> dict[str, Any]:
        if not self._connected:
            return {"status": "simulated", "ticket": ticket}

        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "error", "message": f"Position not found: {ticket}"}
        pos = positions[0]
        close_vol = float(volume or pos.volume)
        close_vol = min(close_vol, float(pos.volume))
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return {"status": "error", "message": f"No tick for {pos.symbol}"}

        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = float(tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": close_vol,
            "type": order_type,
            "price": price,
            "deviation": DEVIATION,
            "magic": MAGIC,
            "comment": "QuantAI close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        with self._io_lock:
            result = self._order_send(request)
        if result.get("status") == "ok":
            remaining = max(0.0, float(pos.volume) - close_vol)
            still_open = mt5.positions_get(ticket=ticket)
            if still_open:
                remaining = float(still_open[0].volume)
            else:
                remaining = 0.0
            result.update({
                "action": "TRADE",
                "type": "CLOSE",
                "ticket": ticket,
                "remaining_volume": remaining,
            })
        return result

    def reduce_position(self, ticket: int, volume: float, symbol: str = "") -> dict[str, Any]:
        return self.close_position(ticket, volume=volume)

    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        if not self._connected:
            return {"status": "simulated", "ticket": ticket}

        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "error", "message": f"Position not found: {ticket}"}
        pos = positions[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": sl if sl is not None else float(pos.sl),
            "tp": tp if tp is not None else float(pos.tp),
        }
        with self._io_lock:
            result = self._order_send(request)
        if result.get("status") == "ok":
            result.update({"action": "TRADE", "type": "MODIFY", "ticket": ticket, "sl": sl, "tp": tp})
        return result

    def close_all(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "simulated", "closed": 0}
        closed = 0
        failed = 0
        for pos in list(self.get_positions()):
            result = self.close_position(int(pos["ticket"]))
            if result.get("status") == "ok":
                closed += 1
            else:
                failed += 1
        return {"status": "ok", "action": "CLOSE_ALL", "closed": closed, "failed": failed}

    def close(self) -> None:
        self._connected = False
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._mt5 = None


__all__ = ["Mt5DirectConnector", "account_equity"]
