"""ZeroMQ bridge to MetaTrader 5."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 10000
MAX_RECONNECT_ATTEMPTS = 3


class ZeroMQConnector:
    """Communicates with MT5 via ZeroMQ PUSH/PULL/SUB sockets.

    Ports: 32768 (commands), 32769 (confirmations), 32770 (tick data)
    """

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
        self._ctx: Any = None
        self._push_socket: Any = None
        self._pull_socket: Any = None
        self._sub_socket: Any = None

    def connect(self) -> bool:
        try:
            import zmq

            self._ctx = zmq.Context()
            self._push_socket = self._ctx.socket(zmq.PUSH)
            self._push_socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
            self._push_socket.setsockopt(zmq.LINGER, 0)
            self._push_socket.connect(f"tcp://{self.host}:{self.command_port}")
            self._pull_socket = self._ctx.socket(zmq.PULL)
            self._pull_socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
            self._pull_socket.setsockopt(zmq.LINGER, 0)
            self._pull_socket.connect(f"tcp://{self.host}:{self.confirm_port}")
            self._sub_socket = self._ctx.socket(zmq.SUB)
            self._sub_socket.setsockopt(zmq.LINGER, 0)
            self._sub_socket.connect(f"tcp://{self.host}:{self.tick_port}")
            self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
            self._sub_socket.setsockopt(zmq.RCVTIMEO, 1000)
            self._connected = True
            logger.info(
                "ZeroMQ connected to MT5 on %s ports %s-%s",
                self.host,
                self.command_port,
                self.tick_port,
            )
            return True
        except ImportError:
            logger.warning("pyzmq not installed — running in simulation mode")
            return False
        except Exception:
            logger.error("ZeroMQ connection failed", exc_info=True)
            return False

    def reconnect(self) -> bool:
        self.close()
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            logger.info("Reconnect attempt %d/%d", attempt + 1, MAX_RECONNECT_ATTEMPTS)
            if self.connect():
                return True
            time.sleep(1.0 * (attempt + 1))
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _send_command(self, command: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"status": "simulated", **command}

        import zmq

        try:
            self._push_socket.send_string(json.dumps(command))
            response = self._pull_socket.recv_string()
            return json.loads(response)
        except zmq.Again:
            logger.warning("ZeroMQ timeout after %dms for %s", self.timeout_ms, command.get("action"))
            return {"status": "error", "message": "Request timed out", "action": command.get("action")}
        except Exception:
            logger.warning("ZeroMQ send failed — attempting reconnect")
            if self.reconnect():
                self._push_socket.send_string(json.dumps(command))
                response = self._pull_socket.recv_string()
                return json.loads(response)
            return {"status": "error", "message": "Connection lost"}

    def send_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        ticket: int | None = None,
    ) -> dict[str, Any]:
        if not self._connected:
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

        result = self._send_command(command)
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

    def get_account_info(self) -> dict[str, Any]:
        if not self._connected:
            return {
                "equity": 1_000_000,
                "balance": 1_000_000,
                "margin": 0,
                "free_margin": 1_000_000,
                "gross_exposure": 0,
                "largest_position_pct": 0,
            }
        return self._send_command({"action": "ACCOUNT"})

    def get_ohlcv(self, symbol: str, timeframe: str = "M15", count: int = 200) -> pd.DataFrame | None:
        if not self._connected:
            return None

        result = self._send_command({
            "action": "DATA",
            "symbol": symbol,
            "timeframe": timeframe,
            "count": count,
        })
        if result.get("status") != "ok":
            logger.warning("DATA request failed for %s: %s", symbol, result.get("message"))
            return None

        bars = result.get("bars", [])
        if not bars:
            return None

        df = pd.DataFrame(bars)
        df = df.rename(columns={"time": "timestamp"})
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        result = self._send_command({"action": "POSITIONS"})
        if result.get("status") != "ok":
            return []
        return result.get("positions", [])

    def close_all(self) -> dict[str, Any]:
        if not self._connected:
            logger.info("SIM CLOSE_ALL")
            return {"status": "simulated", "closed": 0}
        return self._send_command({"action": "CLOSE_ALL"})

    def close_position(self, ticket: int) -> dict[str, Any]:
        if not self._connected:
            logger.info("SIM CLOSE ticket=%d", ticket)
            return {
                "status": "simulated",
                "ticket": ticket,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
            }
        return self.send_trade(symbol="", direction="CLOSE", volume=0, ticket=ticket)

    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        if not self._connected:
            logger.info("SIM MODIFY ticket=%d sl=%s tp=%s", ticket, sl, tp)
            return {
                "status": "simulated",
                "ticket": ticket,
                "slippage": 0.0,
                "fill_rate": 1.0,
                "latency_ms": 0,
            }
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
        if not self._connected or not self._sub_socket:
            return None
        try:
            msg = self._sub_socket.recv_string()
            return json.loads(msg)
        except Exception:
            return None

    def close(self) -> None:
        self._connected = False
        for sock in (self._push_socket, self._pull_socket, self._sub_socket):
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
        if self._ctx is not None:
            try:
                self._ctx.term()
            except Exception:
                pass
        self._ctx = None
        self._push_socket = None
        self._pull_socket = None
        self._sub_socket = None
