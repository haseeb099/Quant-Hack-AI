"""Background operator watchdog loop for live engine + dashboard."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from src.operator.watchdog import run_operator_watchdog_cycle

logger = logging.getLogger(__name__)


def watchdog_interval_sec() -> int:
    return max(30, int(os.getenv("OPERATOR_WATCHDOG_INTERVAL_SEC", "60")))


def watchdog_dashboard_url(port: int = 8080) -> str:
    return os.getenv("OPERATOR_DASHBOARD_URL", f"http://127.0.0.1:{port}").rstrip("/")


def run_watchdog_loop(
    *,
    interval_sec: int | None = None,
    dashboard_url: str | None = None,
) -> None:
    interval = interval_sec or watchdog_interval_sec()
    url = dashboard_url or watchdog_dashboard_url()
    logger.info("Operator watchdog loop started — interval=%ss url=%s", interval, url)
    while True:
        try:
            snapshot = run_operator_watchdog_cycle(
                dashboard_url=url,
                persist=True,
                dispatch_alerts=True,
            )
            status = snapshot.get("status", "UNKNOWN")
            summary = snapshot.get("summary", {})
            logger.info(
                "Watchdog cycle %s — mt5=%s engine=%s orphans=%s",
                status,
                summary.get("mt5_position_count"),
                summary.get("engine_position_count"),
                summary.get("orphan_trades"),
            )
        except Exception:
            logger.exception("Operator watchdog cycle failed")
        time.sleep(interval)


def start_watchdog_thread(
    *,
    interval_sec: int | None = None,
    dashboard_url: str | None = None,
) -> Any:
    import threading

    thread = threading.Thread(
        target=run_watchdog_loop,
        kwargs={
            "interval_sec": interval_sec,
            "dashboard_url": dashboard_url,
        },
        daemon=True,
        name="quantai-operator-watchdog",
    )
    thread.start()
    return thread


def watchdog_enabled_for_mode(mode: str, with_dashboard: bool) -> bool:
    if os.getenv("OPERATOR_WATCHDOG_ENABLED", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    if os.getenv("OPERATOR_WATCHDOG_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return mode == "live" and with_dashboard
