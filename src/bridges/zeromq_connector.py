"""ZeroMQ bridge to MetaTrader 5."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Any

import pandas as pd

from src.bridges.positions_snapshot import PositionsSnapshot

logger = logging.getLogger(__name__)

FILL_RECOVERY_POLL_SEC = float(os.getenv("ZMQ_FILL_RECOVERY_POLL_SEC", "0.5"))
FILL_RECOVERY_POLLS = int(os.getenv("ZMQ_FILL_RECOVERY_POLLS", "20"))
VOLUME_EPS = 1e-4

DEFAULT_TIMEOUT_MS = 10000
DATA_TIMEOUT_MS = int(os.getenv("ZMQ_DATA_TIMEOUT_MS", "15000"))
TRADE_TIMEOUT_MS = int(os.getenv("ZMQ_TRADE_TIMEOUT_MS", "60000"))
TRADE_ACK_TIMEOUT_MS = int(os.getenv("ZMQ_TRADE_ACK_TIMEOUT_MS", "12000"))
MAX_RECONNECT_ATTEMPTS = 3
TRADE_MAX_RETRIES = 3
ZMQ_WARMUP_SEC = float(os.getenv("ZMQ_WARMUP_SEC", "2.0"))
ZMQ_VERIFY_RETRIES = int(os.getenv("ZMQ_VERIFY_RETRIES", "3"))
OHLCV_BAR_COUNT = int(os.getenv("ZMQ_OHLCV_BAR_COUNT", "320"))

_MT5_TO_DISPLAY_SYMBOL = {
    "AUDUSD": "AUD/USD",
    "EURCHF": "EUR/CHF",
    "EURGBP": "EUR/GBP",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDCAD": "USD/CAD",
    "USDCHF": "USD/CHF",
    "USDJPY": "USD/JPY",
    "XAGUSD": "XAG/USD",
    "XAUUSD": "XAU/USD",
    "BARUSD": "BAR/USD",
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "SOLUSD": "SOL/USD",
    "XRPUSD": "XRP/USD",
}


def account_equity(account: dict[str, Any], *, simulation: bool) -> float | None:
    """Return equity for risk sizing; None in live when bridge response is invalid."""
    if simulation or account.get("status") == "simulated":
        raw = account.get("equity")
        if raw is not None:
            return float(raw)
        return 1_000_000.0
    status = account.get("status", "ok")
    equity = account.get("equity")
    if status != "ok" or equity is None:
        return None
    return float(equity)


class ZeroMQConnector:
    """Communicates with MT5 via ZeroMQ PUSH/PULL/SUB sockets.

    Ports: 32768 (commands), 32769 (confirmations), 32770 (tick data)
    """

    bridge_type = "zmq"

    def __init__(
        self,
        command_port: int | None = None,
        confirm_port: int | None = None,
        tick_port: int | None = None,
        host: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.host = host or os.getenv("ZMQ_HOST", "127.0.0.1")
        self.command_port = command_port or int(os.getenv("ZMQ_COMMAND_PORT", "32768"))
        self.confirm_port = confirm_port or int(os.getenv("ZMQ_CONFIRM_PORT", "32769"))
        self.tick_port = tick_port or int(os.getenv("ZMQ_TICK_PORT", "32770"))
        self.timeout_ms = timeout_ms
        self._connected = False
        self._bridge_responding = False
        self._sockets_ready = False
        self._last_error: str = ""
        self._ctx: Any = None
        self._push_socket: Any = None
        self._pull_socket: Any = None
        self._sub_socket: Any = None
        self._io_lock = threading.RLock()

    def _open_sockets(self) -> bool:
        import zmq

        self._ctx = zmq.Context()
        # Connect confirmation (PULL) before command (PUSH) so the EA can always reply.
        self._pull_socket = self._ctx.socket(zmq.PULL)
        self._pull_socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self._pull_socket.setsockopt(zmq.LINGER, 0)
        self._pull_socket.connect(f"tcp://{self.host}:{self.confirm_port}")
        self._push_socket = self._ctx.socket(zmq.PUSH)
        self._push_socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        self._push_socket.setsockopt(zmq.LINGER, 0)
        self._push_socket.connect(f"tcp://{self.host}:{self.command_port}")
        self._sub_socket = self._ctx.socket(zmq.SUB)
        self._sub_socket.setsockopt(zmq.LINGER, 0)
        self._sub_socket.connect(f"tcp://{self.host}:{self.tick_port}")
        self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._sub_socket.setsockopt(zmq.RCVTIMEO, 1000)
        self._sockets_ready = True
        return True

    def health_check(self) -> tuple[bool, str]:
        """Ping MT5 — prefer Python API to avoid contending with TRADE on ZMQ confirm socket."""
        mt5_account = self._account_from_mt5()
        if mt5_account is not None:
            self._bridge_responding = True
            self._last_error = ""
            return True, "ok"
        if not self._push_socket or not self._pull_socket:
            return False, "sockets not open"
        result = self._send_command({"action": "ACCOUNT"})
        if result.get("status") == "ok" and "equity" in result:
            self._bridge_responding = True
            self._last_error = ""
            return True, "ok"
        message = result.get("message", "EA did not respond")
        self._bridge_responding = False
        self._last_error = message
        return False, message

    def connect(self) -> bool:
        try:
            import zmq  # noqa: F401
        except ImportError:
            logger.warning("pyzmq not installed — running in simulation mode")
            return False

        with self._io_lock:
            try:
                self.close()
                self._open_sockets()
                time.sleep(ZMQ_WARMUP_SEC)
                self._drain_pull_socket()

                for attempt in range(1, ZMQ_VERIFY_RETRIES + 1):
                    ok, detail = self.health_check()
                    if ok:
                        self._connected = True
                        logger.info(
                            "ZeroMQ bridge verified on %s ports %s-%s (attempt %d)",
                            self.host,
                            self.command_port,
                            self.tick_port,
                            attempt,
                        )
                        return True
                    logger.warning(
                        "ZeroMQ verify attempt %d/%d failed: %s",
                        attempt,
                        ZMQ_VERIFY_RETRIES,
                        detail,
                    )
                    time.sleep(1.0)

                self._connected = False
                self._bridge_responding = False
                self._last_error = (
                    "Ports may be open but DWX_ZeroMQ_Server is not responding. "
                    "In MT5: Navigator -> Services -> stop and restart DWX_ZeroMQ_Server, "
                    "then enable Algorithmic Trading."
                )
                logger.error(self._last_error)
                self.close()
                return False
            except Exception:
                self._connected = False
                self._bridge_responding = False
                logger.error("ZeroMQ connection failed", exc_info=True)
                return False

    def reconnect(self) -> bool:
        with self._io_lock:
            self.close()
            for attempt in range(MAX_RECONNECT_ATTEMPTS):
                logger.info("Reconnect attempt %d/%d", attempt + 1, MAX_RECONNECT_ATTEMPTS)
                if self.connect():
                    return True
                time.sleep(1.0 * (attempt + 1))
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._bridge_responding

    @property
    def bridge_responding(self) -> bool:
        return self._bridge_responding

    @property
    def last_error(self) -> str:
        return self._last_error

    def refresh_health(self) -> bool:
        """Re-verify EA response; reconnect if sockets were never verified."""
        if not self._sockets_ready:
            return self.connect()
        ok, _ = self.health_check()
        if ok:
            self._connected = True
            return True
        return self.reconnect()

    def _drain_pull_socket(self, max_messages: int = 8) -> None:
        """Discard stale confirmations left on the PULL socket from prior sessions."""
        if not self._pull_socket:
            return
        import zmq

        original_timeout = self._pull_socket.getsockopt(zmq.RCVTIMEO)
        self._pull_socket.setsockopt(zmq.RCVTIMEO, 0)
        try:
            for _ in range(max_messages):
                try:
                    self._pull_socket.recv_string(zmq.NOBLOCK)
                except zmq.Again:
                    break
        finally:
            self._pull_socket.setsockopt(zmq.RCVTIMEO, original_timeout)

    def _send_command(self, command: dict[str, Any], *, drain_stale: bool | None = None) -> dict[str, Any]:
        if not self._sockets_ready:
            return {
                "status": "error",
                "message": "ZeroMQ sockets not ready",
                "action": command.get("action"),
            }

        with self._io_lock:
            return self._send_command_unlocked(command, drain_stale=drain_stale)

    def _drain_stale_before_trade(self) -> int:
        """Clear queued DATA/ACCOUNT responses so TRADE confirmations are not starved."""
        import zmq

        if not self._sockets_ready:
            return 0
        original = self._pull_socket.getsockopt(zmq.RCVTIMEO)
        self._pull_socket.setsockopt(zmq.RCVTIMEO, 30)
        drained = 0
        try:
            for _ in range(64):
                try:
                    response = self._pull_socket.recv_string()
                    try:
                        result = json.loads(response)
                    except json.JSONDecodeError:
                        drained += 1
                        continue
                    if result.get("action") == "TRADE":
                        logger.warning(
                            "Discarded stale TRADE response before new trade: %s",
                            result.get("type"),
                        )
                    drained += 1
                except zmq.Again:
                    break
        finally:
            self._pull_socket.setsockopt(zmq.RCVTIMEO, original)
        return drained

    def _send_command_unlocked(
        self,
        command: dict[str, Any],
        *,
        drain_stale: bool | None = None,
    ) -> dict[str, Any]:
        import zmq

        expected_action = command.get("action")
        if drain_stale is None:
            # Never discard TRADE confirmations — timeouts + drain caused duplicate fills.
            drain_stale = expected_action != "TRADE"

        original_rcv_timeout = self._pull_socket.getsockopt(zmq.RCVTIMEO)
        trade_timeout = max(self.timeout_ms, TRADE_ACK_TIMEOUT_MS)
        if expected_action == "TRADE":
            drained = self._drain_stale_before_trade()
            if drained:
                logger.info("Drained %d stale ZMQ messages before TRADE", drained)
            self._pull_socket.setsockopt(zmq.RCVTIMEO, trade_timeout)

        def _recv_matching() -> dict[str, Any]:
            max_reads = 32 if expected_action == "TRADE" else (16 if expected_action else 1)
            for read in range(max_reads):
                try:
                    response = self._pull_socket.recv_string()
                    result = json.loads(response)
                    if expected_action and result.get("action") != expected_action:
                        logger.warning(
                            "ZeroMQ stale response for %s (got %s) — read %d/%d",
                            expected_action,
                            result.get("action"),
                            read + 1,
                            max_reads,
                        )
                        continue
                    return result
                except zmq.Again:
                    return {
                        "status": "error",
                        "message": "Request timed out",
                        "action": expected_action,
                    }
            return {
                "status": "error",
                "message": f"No matching response for {expected_action}",
                "action": expected_action,
            }

        try:
            if drain_stale:
                self._drain_pull_socket(max_messages=16)
            self._push_socket.send_string(json.dumps(command))
            return _recv_matching()
        except Exception as exc:
            logger.warning("ZeroMQ command failed for %s: %s", expected_action, exc)
            return {
                "status": "error",
                "message": str(exc),
                "action": expected_action,
            }
        finally:
            if expected_action == "TRADE":
                self._pull_socket.setsockopt(zmq.RCVTIMEO, original_rcv_timeout)

    def _is_retryable(self, result: dict[str, Any]) -> bool:
        if result.get("status") == "ok":
            return False
        message = str(result.get("message", "")).lower()
        return any(
            token in message
            for token in ("timeout", "timed out", "requote", "price changed", "invalid price", "busy", "retry")
        )

    @staticmethod
    def _normalize_symbol_key(symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def _mt5_volume_for_symbol_direction(self, symbol: str, direction: str) -> float | None:
        positions = self._positions_from_mt5()
        if positions is None:
            return None
        target = self._normalize_symbol_key(symbol)
        dir_u = direction.upper()
        total = 0.0
        for pos in positions:
            if self._normalize_symbol_key(str(pos.get("symbol", ""))) != target:
                continue
            if str(pos.get("type", "")).upper() == dir_u:
                total += float(pos.get("volume", 0))
        return total

    def _recover_open_trade_result(
        self,
        symbol: str,
        direction: str,
        baseline_volume: float,
        requested_volume: float,
    ) -> dict[str, Any] | None:
        current = self._mt5_volume_for_symbol_direction(symbol, direction)
        if current is None or current < baseline_volume + requested_volume - VOLUME_EPS:
            return None
        positions = self._positions_from_mt5() or []
        target = self._normalize_symbol_key(symbol)
        dir_u = direction.upper()
        ticket: int | None = None
        price = 0.0
        for pos in positions:
            if self._normalize_symbol_key(str(pos.get("symbol", ""))) != target:
                continue
            if str(pos.get("type", "")).upper() != dir_u:
                continue
            ticket = int(pos.get("ticket", 0)) or None
            price = float(pos.get("price_open", 0) or 0)
            break
        return {
            "status": "ok",
            "action": "TRADE",
            "symbol": symbol,
            "type": direction,
            "volume": requested_volume,
            "ticket": ticket,
            "price": price,
            "slippage": 0.0,
            "fill_rate": 1.0,
            "latency_ms": 0,
            "recovered": True,
        }

    def _poll_recovered_open_trade(
        self,
        symbol: str,
        direction: str,
        baseline_volume: float,
        requested_volume: float,
    ) -> dict[str, Any] | None:
        for _ in range(FILL_RECOVERY_POLLS):
            recovered = self._recover_open_trade_result(
                symbol,
                direction,
                baseline_volume,
                requested_volume,
            )
            if recovered is not None:
                return recovered
            time.sleep(FILL_RECOVERY_POLL_SEC)
        return None

    def _send_open_trade_idempotent(
        self,
        command: dict[str, Any],
        *,
        symbol: str,
        direction: str,
        volume: float,
        baseline_volume: float | None,
    ) -> dict[str, Any]:
        baseline = baseline_volume if baseline_volume is not None else 0.0
        last: dict[str, Any] = {"status": "error", "message": "No trade attempt", "action": "TRADE"}

        for attempt in range(TRADE_MAX_RETRIES):
            if attempt > 0:
                recovered = self._recover_open_trade_result(
                    symbol,
                    direction,
                    baseline,
                    volume,
                )
                if recovered is not None:
                    logger.warning(
                        "Recovered filled TRADE %s %s vol=%.4f without resend (attempt %d)",
                        direction,
                        symbol,
                        volume,
                        attempt + 1,
                    )
                    return recovered

            last = self._send_command(command, drain_stale=False)
            if last.get("status") == "ok":
                return last
            if not self._is_retryable(last):
                break

            recovered = self._poll_recovered_open_trade(symbol, direction, baseline, volume)
            if recovered is not None:
                logger.warning(
                    "TRADE response lost but MT5 fill confirmed for %s %s vol=%.4f",
                    direction,
                    symbol,
                    volume,
                )
                return recovered

            if attempt < TRADE_MAX_RETRIES - 1:
                logger.warning(
                    "ZeroMQ retry %d/%d for %s: %s",
                    attempt + 1,
                    TRADE_MAX_RETRIES,
                    direction,
                    last.get("message"),
                )
                time.sleep(0.5 * (attempt + 1))
                continue

            logger.warning(
                "ZeroMQ retry %d/%d for %s: %s",
                attempt + 1,
                TRADE_MAX_RETRIES,
                direction,
                last.get("message"),
            )
            break

        recovered = self._poll_recovered_open_trade(symbol, direction, baseline, volume)
        if recovered is not None:
            logger.warning(
                "TRADE failed in ZMQ but MT5 fill confirmed for %s %s vol=%.4f",
                direction,
                symbol,
                volume,
            )
            return recovered
        return last

    def _mt5_volume_for_ticket(self, ticket: int) -> float | None:
        positions = self._positions_from_mt5()
        if positions is None:
            return None
        for pos in positions:
            if int(pos.get("ticket", 0)) == ticket:
                return float(pos.get("volume", 0))
        return 0.0

    def _recover_close_result(
        self,
        ticket: int,
        before_volume: float,
        close_volume: float,
        *,
        full_close: bool,
    ) -> dict[str, Any] | None:
        current = self._mt5_volume_for_ticket(ticket)
        if current is None:
            return None
        if full_close or close_volume >= before_volume - VOLUME_EPS:
            if current <= VOLUME_EPS:
                return {
                    "status": "ok",
                    "action": "TRADE",
                    "type": "CLOSE",
                    "ticket": ticket,
                    "volume": before_volume,
                    "remaining_volume": 0.0,
                    "slippage": 0.0,
                    "fill_rate": 1.0,
                    "latency_ms": 0,
                    "recovered": True,
                }
            return None
        expected = max(before_volume - close_volume, 0.0)
        if current <= expected + VOLUME_EPS:
            return {
                "status": "ok",
                "action": "TRADE",
                "type": "CLOSE_PARTIAL",
                "ticket": ticket,
                "volume": close_volume,
                "remaining_volume": current,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
                "recovered": True,
            }
        return None

    def _poll_recovered_close(
        self,
        ticket: int,
        before_volume: float,
        close_volume: float,
        *,
        full_close: bool,
    ) -> dict[str, Any] | None:
        for _ in range(FILL_RECOVERY_POLLS):
            recovered = self._recover_close_result(
                ticket,
                before_volume,
                close_volume,
                full_close=full_close,
            )
            if recovered is not None:
                return recovered
            time.sleep(FILL_RECOVERY_POLL_SEC)
        return None

    def _send_close_idempotent(
        self,
        command: dict[str, Any],
        *,
        ticket: int,
        before_volume: float,
        close_volume: float,
        full_close: bool,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {"status": "error", "message": "No close attempt", "action": "TRADE"}

        for attempt in range(TRADE_MAX_RETRIES):
            if attempt > 0:
                recovered = self._recover_close_result(
                    ticket,
                    before_volume,
                    close_volume,
                    full_close=full_close,
                )
                if recovered is not None:
                    logger.warning(
                        "Recovered CLOSE ticket=%d without resend (attempt %d)",
                        ticket,
                        attempt + 1,
                    )
                    return recovered

            last = self._send_command(command, drain_stale=False)
            if last.get("status") == "ok":
                return last
            if not self._is_retryable(last):
                break

            recovered = self._poll_recovered_close(
                ticket,
                before_volume,
                close_volume,
                full_close=full_close,
            )
            if recovered is not None:
                logger.warning(
                    "Close response lost but MT5 confirms ticket=%d reduced",
                    ticket,
                )
                return recovered

            logger.warning(
                "ZeroMQ retry %d/%d for %s ticket=%d: %s",
                attempt + 1,
                TRADE_MAX_RETRIES,
                command.get("type"),
                ticket,
                last.get("message"),
            )
            time.sleep(0.2 * (attempt + 1))

        recovered = self._poll_recovered_close(
            ticket,
            before_volume,
            close_volume,
            full_close=full_close,
        )
        if recovered is not None:
            logger.warning(
                "Close failed in ZMQ but MT5 confirms ticket=%d reduced",
                ticket,
            )
            return recovered
        return last

    def _send_with_retry(
        self,
        command: dict[str, Any],
        *,
        escalate_close_ticket: int | None = None,
    ) -> dict[str, Any]:
        last: dict[str, Any] = command
        trade_type = str(command.get("type", "")).upper()
        is_open = trade_type in ("BUY", "SELL")
        symbol = str(command.get("symbol", ""))
        direction = trade_type if is_open else ""
        volume = float(command.get("volume", 0) or 0)
        baseline: float | None = None
        if is_open and symbol:
            baseline = self._mt5_volume_for_symbol_direction(symbol, direction)
            if baseline is None:
                logger.warning(
                    "Cannot read MT5 baseline for %s — open-trade idempotency reduced",
                    symbol,
                )
                baseline = 0.0
            return self._send_open_trade_idempotent(
                command,
                symbol=symbol,
                direction=direction,
                volume=volume,
                baseline_volume=baseline,
            )

        is_close = trade_type in ("CLOSE", "CLOSE_PARTIAL")
        if is_close:
            ticket = int(command.get("ticket", 0) or 0)
            before_volume = self._mt5_volume_for_ticket(ticket) if ticket else None
            if before_volume is not None and ticket > 0:
                close_volume = (
                    volume
                    if trade_type == "CLOSE_PARTIAL" and volume > 0
                    else before_volume
                )
                full_close = (
                    trade_type == "CLOSE"
                    or close_volume >= before_volume - VOLUME_EPS
                )
                return self._send_close_idempotent(
                    command,
                    ticket=ticket,
                    before_volume=before_volume,
                    close_volume=close_volume,
                    full_close=full_close,
                )
            if ticket > 0:
                logger.warning(
                    "Cannot read MT5 volume for ticket %d — close idempotency reduced",
                    ticket,
                )

        for attempt in range(TRADE_MAX_RETRIES):
            last = self._send_command(command, drain_stale=trade_type not in ("CLOSE", "CLOSE_PARTIAL"))
            if last.get("status") == "ok":
                return last
            if not self._is_retryable(last):
                break
            logger.warning(
                "ZeroMQ retry %d/%d for %s: %s",
                attempt + 1,
                TRADE_MAX_RETRIES,
                command.get("type") or command.get("action"),
                last.get("message"),
            )
            time.sleep(0.2 * (attempt + 1))

        if escalate_close_ticket is not None:
            logger.warning(
                "Escalating to full close for ticket %d after reduce failure",
                escalate_close_ticket,
            )
            return self.close_position(escalate_close_ticket)
        return last

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

    @staticmethod
    def _resolve_position_ticket(symbol: str, order_ticket: int) -> int:
        """Map order/deal id to an open position ticket on the symbol."""
        positions = ZeroMQConnector._positions_from_mt5() or []
        if not positions:
            return order_ticket
        target = ZeroMQConnector._normalize_symbol_key(symbol)
        matching = [
            p for p in positions
            if ZeroMQConnector._normalize_symbol_key(str(p.get("symbol", ""))) == target
        ]
        if not matching:
            return order_ticket
        if order_ticket and any(int(p.get("ticket", 0)) == order_ticket for p in matching):
            return order_ticket
        latest = max(matching, key=lambda p: int(p.get("time", 0) or 0))
        return int(latest.get("ticket", order_ticket) or order_ticket)

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
        if not self.is_connected:
            logger.info("SIM TRADE: %s %s %.4f", direction, symbol, volume)
            return {
                "status": "simulated",
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
            }

        specs = self._symbol_specs_from_mt5(symbol) or self.get_symbol_info(symbol)
        volume = self._normalize_volume(volume, specs)

        command: dict[str, Any] = {
            "action": "TRADE",
            "symbol": symbol,
            "type": direction,
            "volume": volume,
        }
        if sl is not None:
            command["sl"] = sl
        if tp is not None:
            command["tp"] = tp
        if ticket is not None:
            command["ticket"] = ticket
        if entry_mode == "limit" and limit_price is not None and limit_price > 0:
            command["entry_mode"] = "limit"
            command["limit_price"] = limit_price

        result = self._send_with_retry(command)
        if result.get("status") == "ok" and direction.upper() in ("BUY", "SELL"):
            pos_ticket = self._resolve_position_ticket(symbol, int(result.get("ticket", 0) or 0))
            if pos_ticket:
                result["ticket"] = pos_ticket
            filled = result.get("volume")
            if filled is not None:
                result["volume"] = float(filled)
        if result.get("status") == "ok":
            logger.info(
                "Trade executed: %s %s vol=%.4f slippage=%.5f latency=%dms",
                direction,
                symbol,
                volume,
                result.get("slippage", 0),
                result.get("latency_ms", 0),
            )
        return result

    def reduce_position(self, ticket: int, volume: float, symbol: str = "") -> dict[str, Any]:
        """Partial or full close by ticket — never a naked opposite deal."""
        if not self.is_connected:
            logger.info("SIM REDUCE ticket=%d vol=%.4f", ticket, volume)
            return {
                "status": "simulated",
                "type": "CLOSE_PARTIAL",
                "ticket": ticket,
                "volume": volume,
                "remaining_volume": 0.0,
                "slippage": 0.0,
                "latency_ms": 0,
            }

        specs = self.get_symbol_info(symbol) if symbol else None
        norm_vol = self._normalize_volume(volume, specs)
        command: dict[str, Any] = {
            "action": "TRADE",
            "type": "CLOSE_PARTIAL",
            "ticket": ticket,
            "volume": norm_vol,
        }
        if symbol:
            command["symbol"] = symbol

        result = self._send_with_retry(command, escalate_close_ticket=ticket)
        if result.get("status") == "ok":
            logger.info(
                "Reduced ticket=%d by %.4f remaining=%.4f",
                ticket,
                norm_vol,
                result.get("remaining_volume", 0),
            )
        return result

    def cancel_pending_order(self, order_ticket: int) -> dict[str, Any]:
        if not self.is_connected:
            return {"status": "simulated", "type": "CANCEL_PENDING", "order_ticket": order_ticket}
        return self._send_with_retry({
            "action": "TRADE",
            "type": "CANCEL_PENDING",
            "order_ticket": order_ticket,
        })

    def get_account_info(self) -> dict[str, Any]:
        if not self._sockets_ready:
            return {
                "status": "error",
                "message": "ZeroMQ sockets not ready",
                "action": "ACCOUNT",
            }
        # Prefer MT5 Python API for account reads — avoids stale DATA frames on the ZMQ confirm socket.
        mt5_account = self._account_from_mt5()
        if mt5_account is not None:
            return mt5_account
        result = self._send_command({"action": "ACCOUNT"})
        if result.get("status") == "ok" and result.get("equity") is not None:
            return result
        return result

    @staticmethod
    def _account_from_mt5() -> dict[str, Any] | None:
        """Read-only account snapshot when ZeroMQ confirmation queue is contended."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            acc = mt5.account_info()
            if acc is None:
                return None
            equity = float(acc.equity)
            margin = float(acc.margin)
            positions = mt5.positions_get() or []
            gross = 0.0
            largest_pct = 0.0
            for pos in positions:
                info = mt5.symbol_info(pos.symbol)
                cs = float(getattr(info, "trade_contract_size", 1) or 1)
                val = float(pos.volume) * cs * float(pos.price_open)
                gross += val
                if equity > 0:
                    largest_pct = max(largest_pct, val / equity)
            margin_level = (equity / margin * 100.0) if margin > 0 else 9999.0
            term = mt5.terminal_info()
            trade_allowed = bool(acc.trade_allowed) and bool(getattr(acc, "trade_expert", True))
            if term is not None and not bool(term.trade_allowed) and not trade_allowed:
                logger.warning(
                    "MT5 trading disabled — account API trade_allowed=false "
                    "(check Algo Trading toolbar and EA permissions)",
                )
            elif term is not None and not bool(term.trade_allowed):
                logger.debug(
                    "MT5 toolbar AutoTrading reports OFF but account API trade_allowed=true "
                    "(ZeroMQ service may still execute)",
                )
            return {
                "status": "ok",
                "action": "ACCOUNT",
                "equity": equity,
                "balance": float(acc.balance),
                "margin": margin,
                "free_margin": float(acc.margin_free),
                "gross_exposure": gross,
                "largest_position_pct": largest_pct,
                "margin_level": margin_level,
                "trade_allowed": trade_allowed,
                "latency_ms": 0,
                "source": "mt5_api",
            }
        except Exception:
            logger.debug("MT5 account fallback failed", exc_info=True)
            return None

    @staticmethod
    def _symbol_specs_from_mt5(symbol: str) -> dict[str, float] | None:
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            mt5_sym = symbol.replace("/", "").upper()
            if not mt5.symbol_select(mt5_sym, True):
                return None
            info = mt5.symbol_info(mt5_sym)
            if info is None:
                return None
            return {
                "contract_size": float(info.trade_contract_size),
                "volume_min": float(info.volume_min),
                "volume_step": float(info.volume_step),
                "volume_max": float(info.volume_max),
                "digits": float(info.digits),
                "point": float(info.point),
                "stops_level": float(info.trade_stops_level),
            }
        except Exception:
            logger.debug("MT5 symbol specs failed for %s", symbol, exc_info=True)
            return None

    def get_symbol_info(self, symbol: str) -> dict[str, float] | None:
        specs = self._symbol_specs_from_mt5(symbol)
        if specs:
            return specs
        if not self._sockets_ready:
            return None
        result = self._send_command({"action": "SYMBOL_INFO", "symbol": symbol})
        if result.get("status") != "ok":
            logger.warning("SYMBOL_INFO failed for %s: %s", symbol, result.get("message"))
            return None
        return {
            "contract_size": float(result.get("contract_size", 1)),
            "volume_min": float(result.get("volume_min", 0.01)),
            "volume_step": float(result.get("volume_step", 0.01)),
            "volume_max": float(result.get("volume_max", 100)),
            "digits": float(result.get("digits", 5)),
            "point": float(result.get("point", 0.0001)),
            "stops_level": float(result.get("stops_level", 0)),
        }

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "M15",
        count: int = OHLCV_BAR_COUNT,
    ) -> pd.DataFrame | None:
        if not self._sockets_ready:
            return None

        data_timeout = max(self.timeout_ms, DATA_TIMEOUT_MS)
        original_timeout = self.timeout_ms
        self.timeout_ms = data_timeout
        try:
            result = self._send_command({
                "action": "DATA",
                "symbol": symbol,
                "timeframe": timeframe,
                "count": count,
            })
        finally:
            self.timeout_ms = original_timeout

        if result.get("status") == "ok":
            bars = result.get("bars", [])
            if bars:
                df = pd.DataFrame(bars)
                df = df.rename(columns={"time": "timestamp"})
                for col in ("open", "high", "low", "close", "volume"):
                    if col in df.columns:
                        df[col] = df[col].astype(float)
                if len(df) >= 50:
                    return df

        fallback = self._ohlcv_from_mt5(symbol, timeframe, count)
        if fallback is not None:
            logger.info(
                "OHLCV connector MT5 fallback for %s %s (%d bars)",
                symbol,
                timeframe,
                len(fallback),
            )
            return fallback

        if result.get("status") != "ok":
            logger.warning("DATA request failed for %s: %s", symbol, result.get("message"))
        return None

    @staticmethod
    def _ohlcv_from_mt5(
        symbol: str,
        timeframe: str,
        count: int,
    ) -> pd.DataFrame | None:
        """Read bars from MT5 Python API when ZeroMQ DATA is slow or empty."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            tf_map = {
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            mt5_sym = symbol.replace("/", "").upper()
            tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)
            mt5.symbol_select(mt5_sym, True)
            rates = mt5.copy_rates_from_pos(mt5_sym, tf, 0, count)
            if rates is None or len(rates) == 0:
                rates = mt5.copy_rates_from_pos(mt5_sym, tf, 1, count)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df = df.rename(columns={"time": "timestamp", "tick_volume": "volume"})
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = df[col].astype(float)
            return df if len(df) >= 50 else None
        except Exception:
            logger.debug("MT5 OHLCV fallback failed for %s", symbol, exc_info=True)
            return None

    @staticmethod
    def _display_symbol(mt5_symbol: str) -> str:
        key = mt5_symbol.replace("/", "").upper()
        return _MT5_TO_DISPLAY_SYMBOL.get(key, mt5_symbol)

    @staticmethod
    def _positions_from_mt5() -> list[dict[str, Any]] | None:
        """Read open positions via MT5 Python API when ZMQ queue is contended."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            raw = mt5.positions_get()
            if raw is None:
                return None
            positions: list[dict[str, Any]] = []
            for pos in raw:
                info = mt5.symbol_info(pos.symbol)
                contract_size = float(getattr(info, "trade_contract_size", 1) or 1)
                positions.append(
                    {
                        "ticket": int(pos.ticket),
                        "symbol": ZeroMQConnector._display_symbol(str(pos.symbol)),
                        "volume": float(pos.volume),
                        "profit": float(pos.profit),
                        "price_open": float(pos.price_open),
                        "price_current": float(pos.price_current),
                        "sl": float(pos.sl) if pos.sl else None,
                        "tp": float(pos.tp) if pos.tp else None,
                        "type": "BUY" if int(pos.type) == 0 else "SELL",
                        "contract_size": contract_size,
                        "time": int(getattr(pos, "time", 0) or 0),
                        "source": "mt5_api",
                    },
                )
            return positions
        except Exception:
            logger.debug("MT5 positions fallback failed", exc_info=True)
            return None

    def get_positions_snapshot(self) -> PositionsSnapshot:
        fallback = self._positions_from_mt5()
        if fallback is not None:
            return PositionsSnapshot(fallback, trusted=True)

        if not self._sockets_ready:
            return PositionsSnapshot([], trusted=False)

        result = self._send_command({"action": "POSITIONS"})
        if result.get("status") == "ok":
            return PositionsSnapshot(result.get("positions") or [], trusted=True)

        logger.warning("Positions unavailable from ZMQ and MT5 API — fail-closed")
        return PositionsSnapshot([], trusted=False)

    def get_positions(self) -> list[dict[str, Any]]:
        return self.get_positions_snapshot().positions

    def close_all(self) -> dict[str, Any]:
        if not self.is_connected:
            logger.info("SIM CLOSE_ALL")
            return {"status": "simulated", "closed": 0}
        return self._send_command({"action": "CLOSE_ALL"})

    def close_position(self, ticket: int, volume: float | None = None) -> dict[str, Any]:
        if not self.is_connected:
            logger.info("SIM CLOSE ticket=%d", ticket)
            return {
                "status": "simulated",
                "ticket": ticket,
                "remaining_volume": 0.0,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
            }
        command: dict[str, Any] = {
            "action": "TRADE",
            "type": "CLOSE",
            "ticket": ticket,
            "volume": volume or 0,
        }
        return self._send_with_retry(command, escalate_close_ticket=None)

    def _modify_position_mt5(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any] | None:
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return None
            pos = positions[0]
            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": str(pos.symbol),
                "sl": float(sl if sl is not None else pos.sl or 0),
                "tp": float(tp if tp is not None else pos.tp or 0),
            }
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                return {"status": "ok", "ticket": ticket, "slippage": 0.0, "latency_ms": 0}
            if result is not None:
                logger.debug(
                    "MT5 modify_position ticket=%d failed: %s %s",
                    ticket,
                    result.retcode,
                    result.comment,
                )
            return None
        except Exception:
            logger.debug("MT5 modify_position failed ticket=%d", ticket, exc_info=True)
            return None

    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        if not self.is_connected:
            logger.info("SIM MODIFY ticket=%d sl=%s tp=%s", ticket, sl, tp)
            return {
                "status": "simulated",
                "ticket": ticket,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
            }
        mt5_result = self._modify_position_mt5(ticket, sl=sl, tp=tp)
        if mt5_result is not None:
            return mt5_result
        command: dict[str, Any] = {
            "action": "TRADE",
            "type": "MODIFY",
            "ticket": ticket,
        }
        if sl is not None:
            command["sl"] = sl
        if tp is not None:
            command["tp"] = tp
        return self._send_command(command)

    def poll_ticks(self) -> dict[str, Any] | None:
        if not self._sockets_ready or not self._sub_socket:
            return None
        # SUB socket is independent of command PUSH/PULL — do not hold _io_lock here or
        # tick polling stalls while ACCOUNT/DATA/POSITIONS commands run.
        import zmq

        try:
            msg = self._sub_socket.recv_string(zmq.NOBLOCK)
            return json.loads(msg)
        except zmq.Again:
            return None
        except Exception:
            return None

    def close(self) -> None:
        self._connected = False
        self._bridge_responding = False
        self._sockets_ready = False
        for sock in (self._push_socket, self._pull_socket, self._sub_socket):
            if sock is not None:
                try:
                    sock.close(linger=0)
                except Exception:
                    pass
        if self._ctx is not None:
            try:
                self._ctx.term()
                time.sleep(0.05)
            except Exception:
                pass
        self._ctx = None
        self._push_socket = None
        self._pull_socket = None
        self._sub_socket = None
