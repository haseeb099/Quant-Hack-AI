"""Shared access to the live trading engine and MT5 bridge for dashboard control."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.bridges.zeromq_connector import ZeroMQConnector
    from src.engine.trading_engine import TradingEngine

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engine: TradingEngine | None = None
_standalone_connector: ZeroMQConnector | None = None


def register_engine(engine: TradingEngine) -> None:
    with _lock:
        global _engine
        _engine = engine
        logger.info("Trading engine registered for dashboard control")


def get_engine() -> TradingEngine | None:
    with _lock:
        return _engine


def get_connector() -> ZeroMQConnector:
    """Return the engine connector when available, else a lazy standalone bridge."""
    with _lock:
        if _engine is not None:
            return _engine.connector
        global _standalone_connector
        if _standalone_connector is None:
            from src.bridges.zeromq_connector import ZeroMQConnector

            _standalone_connector = ZeroMQConnector()
        return _standalone_connector


def control_state() -> dict[str, Any]:
    engine = get_engine()
    state: dict[str, Any] = {
        "engine_available": engine is not None,
        "engine_running": bool(engine and engine.is_running),
        "engine_paused": bool(engine and engine.is_paused),
        "cycle_in_progress": bool(engine and engine.cycle_in_progress),
        "mode": "simulate" if engine and engine.simulation else "live",
    }
    connector = get_connector()
    state["mt5_connected"] = connector.is_connected
    state["zmq_last_error"] = connector.last_error or None
    return state
