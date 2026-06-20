"""Competition compliance engine."""

from __future__ import annotations

import time
from collections import deque
from typing import Any


class ComplianceEngine:
    """Enforces competition-specific rules — frozen, never adapted."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._request_timestamps: deque[float] = deque(maxlen=1000)

    def record_api_request(self) -> bool:
        """Track API rate. Returns False if over limit."""
        now = time.time()
        self._request_timestamps.append(now)
        window = [t for t in self._request_timestamps if now - t < 1.0]
        limit = self.config.get("api_rate_limit_per_sec", 100)
        return len(window) <= limit

    @property
    def single_account_enforced(self) -> bool:
        return self.config.get("single_account", True)
