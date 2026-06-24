"""Fast margin polling — react to stop-out risk within ~1s."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from src.bridges.zeromq_connector import ZeroMQConnector, account_equity
from src.risk.margin_monitor import MarginMonitor, MarginState

logger = logging.getLogger(__name__)


class MarginWatcher:
    """Background poll of account margin; triggers emergency reduce on stop-out risk."""

    def __init__(
        self,
        connector: ZeroMQConnector,
        margin_monitor: MarginMonitor,
        margin_cfg: dict[str, Any],
        *,
        simulation: bool,
        on_reduce_worst_losers: Callable[[int], None],
        on_fail_closed: Callable[[], None],
        is_data_stale: Callable[[], bool] | None = None,
    ) -> None:
        self.connector = connector
        self.margin_monitor = margin_monitor
        self.poll_interval_sec = float(margin_cfg.get("poll_interval_sec", 1))
        self.stale_data_sec = float(margin_cfg.get("stale_data_sec", 10))
        self.simulation = simulation
        self.on_reduce_worst_losers = on_reduce_worst_losers
        self.on_fail_closed = on_fail_closed
        self.is_data_stale = is_data_stale
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_good_at: float = 0.0
        self._equity_miss_streak: int = 0

    def start(self) -> None:
        if self.simulation or self._running:
            return
        self._running = True
        self._last_good_at = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="quantai-margin-watcher")
        self._thread.start()
        logger.info("MarginWatcher started (poll=%.1fs)", self.poll_interval_sec)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self._check()
            except Exception:
                logger.debug("MarginWatcher check failed", exc_info=True)
            time.sleep(self.poll_interval_sec)

    def _check(self) -> None:
        now = time.monotonic()
        if self.is_data_stale and self.is_data_stale():
            if self._last_good_at and (now - self._last_good_at) >= self.stale_data_sec:
                logger.warning(
                    "MarginWatcher: stale market data (FX may be closed) — skipping margin poll",
                )
            return

        account = self.connector.get_account_info()
        equity = account_equity(account, simulation=False)
        if equity is None:
            self._equity_miss_streak += 1
            if self._equity_miss_streak >= 3:
                logger.critical("MarginWatcher: equity unavailable — fail-closed reduce")
                self.on_fail_closed()
            return

        self._equity_miss_streak = 0

        self._last_good_at = now
        margin_state = self.margin_monitor.check(
            equity=equity,
            used_margin=float(account.get("margin", 0)),
            gross_exposure=float(account.get("gross_exposure", 0)),
            largest_position_pct=float(account.get("largest_position_pct", 0)),
            margin_level_pct=account.get("margin_level"),
        )
        if margin_state.close_worst_loser or (
            margin_state.stop_out_risk
            and margin_state.margin_level_pct
            <= self.margin_monitor.margin_cfg.get("stop_out_emergency_pct", 40)
        ):
            logger.warning("MarginWatcher emergency: %s", margin_state.message)
            self.on_reduce_worst_losers(3)
