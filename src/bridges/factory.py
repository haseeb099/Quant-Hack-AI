"""Factory for live MT5 bridge connectors."""

from __future__ import annotations

import logging
import os
import socket
from typing import Any

from src.bridges.mt5_direct_connector import Mt5DirectConnector
from src.bridges.zeromq_connector import ZeroMQConnector

logger = logging.getLogger(__name__)

Connector = ZeroMQConnector | Mt5DirectConnector


def _zmq_ports_open(host: str | None = None) -> bool:
    """Quick TCP probe — avoid hanging ZMQ verify when EA service is down."""
    h = host or os.getenv("ZMQ_HOST", "127.0.0.1")
    ports = (
        int(os.getenv("ZMQ_COMMAND_PORT", "32768")),
        int(os.getenv("ZMQ_CONFIRM_PORT", "32769")),
    )
    for port in ports:
        try:
            with socket.create_connection((h, port), timeout=0.4):
                pass
        except OSError:
            return False
    return True


def create_live_connector() -> Connector:
    """Return ZeroMQ bridge when healthy, otherwise MetaTrader5 direct API."""
    mode = os.getenv("MT5_BRIDGE", "auto").strip().lower()

    if mode == "direct":
        connector = Mt5DirectConnector()
        if not connector.connect():
            raise RuntimeError(f"MT5 direct API failed: {connector.last_error}")
        return connector

    if mode == "zmq":
        connector = ZeroMQConnector()
        if not connector.connect():
            raise RuntimeError(f"ZeroMQ bridge failed: {connector.last_error}")
        return connector

    if not _zmq_ports_open():
        logger.warning("ZeroMQ ports closed — skipping bridge verify, using MT5 direct API")
        direct = Mt5DirectConnector()
        if direct.connect():
            return direct
        raise RuntimeError(f"ZeroMQ ports closed and MT5 direct API failed: {direct.last_error}")

    os.environ.setdefault("ZMQ_VERIFY_RETRIES", "3")
    os.environ.setdefault("ZMQ_WARMUP_SEC", "2.0")
    zmq = ZeroMQConnector(timeout_ms=10000)
    if zmq.connect():
        logger.info("Using ZeroMQ bridge for live trading")
        return zmq

    detail = zmq.last_error
    zmq.close()
    logger.warning("ZeroMQ unavailable (%s) — falling back to MT5 direct API", detail)

    direct = Mt5DirectConnector()
    if direct.connect():
        return direct

    raise RuntimeError(
        f"Neither ZeroMQ nor MT5 direct API is available. ZMQ: {detail}. Direct: {direct.last_error}"
    )


def connector_bridge_type(connector: Any) -> str:
    return getattr(connector, "bridge_type", "zmq")
