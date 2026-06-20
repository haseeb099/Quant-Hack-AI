"""Peer crowd monitor — tracks competition peer behavior R1-R3."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PeerSnapshot:
    timestamp: str
    round_id: str
    peer_count: int
    avg_return: float
    avg_drawdown: float
    top_performer_return: float
    our_rank_estimate: int
    crowd_bias: str  # "risk_on", "risk_off", "mixed"


@dataclass
class PeerMonitorState:
    snapshots: list[PeerSnapshot] = field(default_factory=list)
    crowd_sentiment: str = "mixed"
    relative_performance: float = 0.0


class PeerMonitor:
    """Monitors peer crowd behavior for adaptive positioning."""

    def __init__(self, round_id: str = "round1") -> None:
        self.round_id = round_id
        self.state = PeerMonitorState()

    def update(self, peer_data: dict[str, Any]) -> PeerSnapshot:
        """Process peer leaderboard data and update crowd sentiment."""
        peer_count = peer_data.get("peer_count", 0)
        avg_return = peer_data.get("avg_return", 0.0)
        avg_dd = peer_data.get("avg_drawdown", 0.0)
        top_return = peer_data.get("top_performer_return", 0.0)
        our_return = peer_data.get("our_return", 0.0)
        our_rank = peer_data.get("our_rank", peer_count)

        if avg_return > 0.05 and avg_dd < 0.08:
            crowd_bias = "risk_on"
        elif avg_return < 0 and avg_dd > 0.10:
            crowd_bias = "risk_off"
        else:
            crowd_bias = "mixed"

        snapshot = PeerSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            round_id=self.round_id,
            peer_count=peer_count,
            avg_return=avg_return,
            avg_drawdown=avg_dd,
            top_performer_return=top_return,
            our_rank_estimate=our_rank,
            crowd_bias=crowd_bias,
        )

        self.state.snapshots.append(snapshot)
        self.state.crowd_sentiment = crowd_bias
        self.state.relative_performance = our_return - avg_return

        logger.info(
            "Peer monitor: crowd=%s, our_return=%.1f%%, avg=%.1f%%, rank=%d",
            crowd_bias, our_return * 100, avg_return * 100, our_rank,
        )
        return snapshot

    def sizing_adjustment(self) -> float:
        """Return sizing multiplier based on crowd behavior."""
        sentiment = self.state.crowd_sentiment
        if sentiment == "risk_on" and self.state.relative_performance < 0:
            return 1.1  # catch up when crowd is aggressive and we're behind
        if sentiment == "risk_off" and self.state.relative_performance > 0:
            return 0.9  # protect gains when crowd retreats
        return 1.0

    def should_increase_aggression(self) -> bool:
        return (
            self.state.crowd_sentiment == "risk_on"
            and self.state.relative_performance < -0.02
            and self.round_id == "round1"
        )
