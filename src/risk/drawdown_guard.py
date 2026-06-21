"""Drawdown circuit breaker — frozen risk constitution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DrawdownState:
    tier: str
    size_multiplier: float
    allow_new_trades: bool
    allow_crypto: bool
    message: str


class DrawdownGuard:
    """Five-tier progressive drawdown protection."""

    TIERS = ("normal", "elevated", "warning", "critical", "emergency")

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.peak_equity: float = 0.0
        self.current_tier: str = "normal"

    def update(self, equity: float) -> DrawdownState:
        if equity > self.peak_equity:
            self.peak_equity = equity

        drawdown = 0.0 if self.peak_equity == 0 else (self.peak_equity - equity) / self.peak_equity
        tier = self._classify(drawdown)
        self.current_tier = tier

        multipliers = self.config.get("size_multipliers", {})
        crypto_blocked = self.config.get("crypto_blocked_at", "warning")
        tier_idx = self.TIERS.index(tier)
        blocked_idx = self.TIERS.index(crypto_blocked) if crypto_blocked in self.TIERS else 2

        return DrawdownState(
            tier=tier,
            size_multiplier=multipliers.get(tier, 0.0),
            allow_new_trades=tier not in ("critical", "emergency"),
            allow_crypto=tier_idx < blocked_idx,
            message=f"Drawdown {drawdown:.1%} — tier: {tier}",
        )

    def _classify(self, drawdown: float) -> str:
        thresholds = self.config
        emergency = thresholds.get("emergency_close", 0.15)
        critical = thresholds.get("critical_max", 0.12)
        warning = thresholds.get("warning_max", 0.12)
        elevated = thresholds.get("elevated_max", 0.10)
        normal = thresholds.get("normal_max", 0.05)

        if drawdown >= emergency:
            return "emergency"
        if drawdown >= critical:
            return "critical"
        if drawdown >= warning:
            return "warning"
        if drawdown >= elevated:
            return "elevated"
        if drawdown >= normal:
            return "elevated"
        return "normal"

    def reset(self, equity: float) -> None:
        self.peak_equity = equity
        self.current_tier = "normal"
