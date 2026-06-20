"""Trade decision and execution journal — CSV + JSONL."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOG_DIR = Path("logs")
JSONL_PATH = LOG_DIR / "trades.jsonl"
CSV_PATH = LOG_DIR / "trades.csv"

CSV_HEADERS = [
    "timestamp",
    "symbol",
    "regime",
    "session",
    "agent_votes",
    "direction",
    "confidence",
    "size",
    "sl",
    "tp",
    "slippage",
    "latency_ms",
    "status",
    "reasoning",
]


class TradeLogger:
    """Append-only trade journal for decisions and executions."""

    def __init__(self, log_dir: Path | str = LOG_DIR) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.log_dir / "trades.jsonl"
        self.csv_path = self.log_dir / "trades.csv"
        self._ensure_csv_header()

    def _ensure_csv_header(self) -> None:
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

    def log(
        self,
        symbol: str,
        regime: str,
        session: str,
        direction: str,
        confidence: float,
        agent_votes: list[Any] | None = None,
        size: float = 0.0,
        sl: float | None = None,
        tp: float | None = None,
        slippage: float = 0.0,
        latency_ms: int = 0,
        status: str = "decision",
        reasoning: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        votes_summary = []
        if agent_votes:
            for v in agent_votes:
                if hasattr(v, "agent_name"):
                    votes_summary.append({
                        "agent": v.agent_name,
                        "direction": str(v.direction),
                        "confidence": v.confidence,
                    })
                elif isinstance(v, dict):
                    votes_summary.append(v)

        record: dict[str, Any] = {
            "timestamp": now,
            "symbol": symbol,
            "regime": regime,
            "session": session,
            "agent_votes": votes_summary,
            "direction": direction,
            "confidence": confidence,
            "size": size,
            "sl": sl,
            "tp": tp,
            "slippage": slippage,
            "latency_ms": latency_ms,
            "status": status,
            "reasoning": reasoning,
        }
        if extra:
            record.update(extra)

        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        row = {k: record.get(k, "") for k in CSV_HEADERS}
        row["agent_votes"] = json.dumps(votes_summary)
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)

        try:
            from src.integrations.notion_sync import get_notion_sync

            get_notion_sync().sync_trade(record)
        except Exception:
            logger.debug("Notion trade sync skipped", exc_info=True)

        logger.debug("Trade logged: %s %s %s", status, symbol, direction)
