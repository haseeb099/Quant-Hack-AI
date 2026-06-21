"""Sharpe-aware position management for competition scoring."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_MINUTES = 15
CLOSE_WINDOW_SECONDS = 120  # 2 min after snapshot
PNL_THRESHOLD = -0.003      # -0.3%
DD_THRESHOLD = 0.05         # 5%


@dataclass
class EquitySnapshot:
    timestamp: datetime
    equity: float


class SharpeGuard:
    """Records equity snapshots and triggers Sharpe-aware exits."""

    def __init__(self, snapshot_interval_minutes: int = SNAPSHOT_INTERVAL_MINUTES) -> None:
        self.snapshot_interval = snapshot_interval_minutes
        self._snapshots: deque[EquitySnapshot] = deque(maxlen=500)
        self._last_snapshot: datetime | None = None
        self._peak_equity: float = 0.0

    def record_equity(self, equity: float) -> bool:
        """Record equity if snapshot interval elapsed. Returns True if snapshot taken."""
        now = datetime.now(timezone.utc)
        if self._last_snapshot is not None:
            elapsed = (now - self._last_snapshot).total_seconds()
            if elapsed < self.snapshot_interval * 60:
                return False

        self._snapshots.append(EquitySnapshot(timestamp=now, equity=equity))
        self._last_snapshot = now
        if equity > self._peak_equity:
            self._peak_equity = equity
        return True

    def current_drawdown(self, equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return (self._peak_equity - equity) / self._peak_equity

    def should_close_for_sharpe(
        self,
        position_pnl_pct: float,
        equity: float,
    ) -> bool:
        """Close losing positions within 2 min of snapshot if PnL < -0.3% and DD > 5%."""
        if not self._last_snapshot:
            return False

        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_snapshot).total_seconds()
        if elapsed > CLOSE_WINDOW_SECONDS:
            return False

        dd = self.current_drawdown(equity)
        if position_pnl_pct < PNL_THRESHOLD and dd > DD_THRESHOLD:
            logger.info(
                "SharpeGuard: close trigger pnl=%.2f%% dd=%.1f%%",
                position_pnl_pct * 100,
                dd * 100,
            )
            return True
        return False

    def compute_running_sharpe(self) -> float:
        if len(self._snapshots) < 2:
            return 0.0

        returns = []
        equities = [s.equity for s in self._snapshots]
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

        if len(returns) < 2:
            return 0.0

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = variance ** 0.5
        if std_r < 1e-9:
            return 0.0
        return mean_r / std_r  # non-annualized 15-min equity returns (competition spec)

    def snapshot_count(self) -> int:
        return len(self._snapshots)
