"""Sharpe-aware position management for competition scoring."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_MINUTES = 15
PNL_THRESHOLD = -0.005     # -0.5% default (Round 3 / Finals)
DD_THRESHOLD = 0.05         # 5%
CONSECUTIVE_BAD_SNAPSHOTS = 2

PHASE_PNL_THRESHOLDS = {
    "round2": -0.008,
    "round3": -0.008,
    "finals": -0.007,
}


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
        self._last_sharpe: float = 0.0
        self.pnl_threshold = PNL_THRESHOLD

    def set_phase(self, phase: str) -> None:
        """Tune loser-cut threshold by competition phase."""
        self.pnl_threshold = PHASE_PNL_THRESHOLDS.get(phase, PNL_THRESHOLD)

    def reset_round(self, equity: float) -> None:
        """Clear round-local Sharpe history on phase transition."""
        self._snapshots.clear()
        self._last_snapshot = None
        self._peak_equity = equity
        self._last_sharpe = 0.0

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
        self._last_sharpe = self.compute_running_sharpe()
        return True

    def current_drawdown(self, equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return (self._peak_equity - equity) / self._peak_equity

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
        return mean_r / std_r

    def _sharpe_deteriorating(self) -> bool:
        if len(self._snapshots) < 3:
            return False
        equities = [s.equity for s in self._snapshots]
        recent_returns = []
        for i in range(max(1, len(equities) - 3), len(equities)):
            if equities[i - 1] > 0:
                recent_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])
        if not recent_returns:
            return False
        recent_mean = sum(recent_returns) / len(recent_returns)
        return self._last_sharpe < 0 or recent_mean < 0

    def _consecutive_negative_returns(self, min_count: int = CONSECUTIVE_BAD_SNAPSHOTS) -> bool:
        if len(self._snapshots) < min_count + 1:
            return False
        equities = [s.equity for s in self._snapshots]
        negatives = 0
        for i in range(len(equities) - 1, 0, -1):
            if equities[i - 1] <= 0:
                continue
            ret = (equities[i] - equities[i - 1]) / equities[i - 1]
            if ret < 0:
                negatives += 1
            else:
                break
            if negatives >= min_count:
                return True
        return False

    def evaluate(
        self,
        positions: list[dict[str, Any]],
        equity: float,
        pnl_pct_fn: Any,
    ) -> list[int]:
        """Return tickets to close when loser + (Sharpe deteriorating or DD breach)."""
        if not positions:
            return []

        dd = self.current_drawdown(equity)
        sharpe_bad = self._sharpe_deteriorating()
        consecutive_bad = self._consecutive_negative_returns()
        if dd <= DD_THRESHOLD and not sharpe_bad and not consecutive_bad:
            return []

        threshold = self.pnl_threshold
        tickets: list[int] = []
        for pos in positions:
            ticket = pos.get("ticket")
            if not ticket:
                continue
            pnl_pct = pnl_pct_fn(pos)
            if pnl_pct < threshold and (sharpe_bad or dd > DD_THRESHOLD or consecutive_bad):
                logger.info(
                    "SharpeGuard: close ticket %s pnl=%.2f%% dd=%.1f%% sharpe_bad=%s",
                    ticket,
                    pnl_pct * 100,
                    dd * 100,
                    sharpe_bad,
                )
                tickets.append(int(ticket))
        return tickets

    def should_close_for_sharpe(
        self,
        position_pnl_pct: float,
        equity: float,
    ) -> bool:
        """Legacy single-position check — prefer evaluate()."""
        dd = self.current_drawdown(equity)
        sharpe_bad = self._sharpe_deteriorating()
        consecutive_bad = self._consecutive_negative_returns()
        return position_pnl_pct < self.pnl_threshold and (
            sharpe_bad or dd > DD_THRESHOLD or consecutive_bad
        )

    def snapshot_count(self) -> int:
        return len(self._snapshots)
