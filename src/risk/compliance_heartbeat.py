"""Compliance heartbeat — sustained violation tracking (5-min interval)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300  # 5 minutes


@dataclass
class ComplianceState:
    risk_discipline_score: int = 100
    active_violations: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


class ComplianceHeartbeat:
    """Background thread tracking sustained compliance violations."""

    MARGIN_90_DURATION = 1800   # 30 min
    MARGIN_95_DURATION = 900    # 15 min
    LEVERAGE_DURATION = 1800      # 30 min
    CONCENTRATION_DURATION = 1800 # 30 min

    def __init__(self, risk_config: dict[str, Any] | None = None) -> None:
        self.risk_config = risk_config or {}
        self._state = ComplianceState()
        self._violation_start: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._metrics_fn: Callable[[], dict[str, float]] | None = None
        self._action_callback: Callable[[list[str]], None] | None = None

    @property
    def state(self) -> ComplianceState:
        return self._state

    def start(
        self,
        metrics_fn: Callable[[], dict[str, float]],
        action_callback: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._metrics_fn = metrics_fn
        self._action_callback = action_callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("ComplianceHeartbeat started (interval=%ds)", INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            if self._metrics_fn:
                try:
                    metrics = self._metrics_fn()
                    actions = self.check(metrics)
                    if actions and self._action_callback:
                        self._action_callback(actions)
                except Exception:
                    logger.warning("ComplianceHeartbeat check failed", exc_info=True)
            self._stop.wait(INTERVAL_SECONDS)

    def check(self, metrics: dict[str, float]) -> list[str]:
        """Evaluate sustained violations and return action list."""
        now = time.time()
        actions: list[str] = []
        violations: list[str] = []

        margin_pct = metrics.get("margin_usage_pct", 0)
        leverage = metrics.get("effective_leverage", 0)
        concentration = metrics.get("concentration_pct", 0)

        if margin_pct > 0.90:
            violations.append("margin_above_90")
            duration = self._track_violation("margin_90", now)
            if duration >= self.MARGIN_90_DURATION:
                actions.append("REDUCE_MARGIN")
                self._state.risk_discipline_score = max(0, self._state.risk_discipline_score - 20)
        else:
            self._clear_violation("margin_90")

        if margin_pct > 0.95:
            duration = self._track_violation("margin_95", now)
            if duration >= self.MARGIN_95_DURATION:
                actions.append("EMERGENCY_CLOSE_ALL")
                self._state.risk_discipline_score = max(0, self._state.risk_discipline_score - 30)
        else:
            self._clear_violation("margin_95")

        if leverage > 28:
            violations.append("leverage_above_28")
            duration = self._track_violation("leverage_28", now)
            if duration >= self.LEVERAGE_DURATION:
                actions.append("REDUCE_LEVERAGE")
                self._state.risk_discipline_score = max(0, self._state.risk_discipline_score - 15)
        else:
            self._clear_violation("leverage_28")

        if concentration > 0.90:
            violations.append("concentration_above_90")
            duration = self._track_violation("concentration_90", now)
            if duration >= self.CONCENTRATION_DURATION:
                actions.append("REDUCE_CONCENTRATION")
                self._state.risk_discipline_score = max(0, self._state.risk_discipline_score - 15)
        else:
            self._clear_violation("concentration_90")

        self._state.active_violations = violations
        self._state.actions = actions

        if actions:
            logger.warning("Compliance actions: %s (score=%d)", actions, self._state.risk_discipline_score)

        return actions

    def _track_violation(self, key: str, now: float) -> float:
        if key not in self._violation_start:
            self._violation_start[key] = now
        return now - self._violation_start[key]

    def _clear_violation(self, key: str) -> None:
        self._violation_start.pop(key, None)
