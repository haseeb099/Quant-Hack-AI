"""Automated Notion sync for trade journal, agent performance, and risk events."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_sync_instance: NotionSync | None = None


def _notion_databases_configured() -> bool:
    return any(
        os.getenv(key, "").strip()
        for key in (
            "NOTION_TRADE_JOURNAL_DS_ID",
            "NOTION_AGENT_PERF_DS_ID",
            "NOTION_RISK_EVENTS_DS_ID",
            "NOTION_TASKS_DS_ID",
        )
    )


def notion_sync_enabled() -> bool:
    """True when sync should run: explicit enable, or auto when key + DS IDs are set."""
    explicit = os.getenv("NOTION_SYNC_ENABLED", "").strip().lower()
    if explicit in ("0", "false", "no"):
        return False
    if explicit in ("1", "true", "yes"):
        return bool(os.getenv("NOTION_API_KEY", "").strip())
    return bool(os.getenv("NOTION_API_KEY", "").strip()) and _notion_databases_configured()


class NotionSync:
    """Sync trading events to Notion databases. No-ops when disabled or misconfigured."""

    def __init__(self) -> None:
        self.enabled = notion_sync_enabled()
        self.api_key = os.getenv("NOTION_API_KEY", "")
        self.trade_journal_ds = os.getenv("NOTION_TRADE_JOURNAL_DS_ID", "")
        self.agent_perf_ds = os.getenv("NOTION_AGENT_PERF_DS_ID", "")
        self.risk_events_ds = os.getenv("NOTION_RISK_EVENTS_DS_ID", "")
        self.tasks_ds = os.getenv("NOTION_TASKS_DS_ID", "")
        self._client: Any = None

        if not self.enabled:
            return
        if not self.api_key:
            logger.debug("Notion sync disabled — NOTION_API_KEY missing")
            self.enabled = False
            return
        try:
            from notion_client import Client

            self._client = Client(auth=self.api_key)
        except ImportError:
            logger.warning("notion-client not installed — Notion sync disabled")
            self.enabled = False
        except Exception:
            logger.warning("Notion client init failed", exc_info=True)
            self.enabled = False

    def _can_sync(self, database_id: str) -> bool:
        return bool(self.enabled and self._client and database_id)

    @staticmethod
    def _title(text: str) -> dict[str, Any]:
        return {"title": [{"text": {"content": text[:2000]}}]}

    @staticmethod
    def _rich_text(text: str) -> dict[str, Any]:
        return {"rich_text": [{"text": {"content": text[:2000]}}]}

    @staticmethod
    def _number(value: float | int) -> dict[str, Any]:
        return {"number": float(value)}

    @staticmethod
    def _select(name: str) -> dict[str, Any]:
        return {"select": {"name": name[:100]}}

    def sync_trade(self, record: dict[str, Any]) -> None:
        if not self._can_sync(self.trade_journal_ds):
            return
        symbol = str(record.get("symbol", ""))
        direction = str(record.get("direction", ""))
        title = f"{symbol} {direction} — {record.get('status', 'decision')}"
        properties: dict[str, Any] = {
            "Name": self._title(title),
            "Symbol": self._rich_text(symbol),
            "Direction": self._select(direction or "HOLD"),
            "Status": self._rich_text(str(record.get("status", ""))),
            "Confidence": self._number(float(record.get("confidence", 0))),
            "Regime": self._rich_text(str(record.get("regime", ""))),
            "Session": self._rich_text(str(record.get("session", ""))),
        }
        self._create_page(self.trade_journal_ds, properties, context="trade journal")

    def sync_agent_performance(self, agent: str, stats: dict[str, Any], trade: dict[str, Any] | None = None) -> None:
        if not self._can_sync(self.agent_perf_ds):
            return
        title = f"{agent} — {stats.get('sample_size', 0)} samples"
        properties: dict[str, Any] = {
            "Name": self._title(title),
            "Agent": self._rich_text(agent),
            "Win Rate": self._number(float(stats.get("win_rate", 0))),
            "Avg R": self._number(float(stats.get("avg_r", 0))),
            "Samples": self._number(int(stats.get("sample_size", 0))),
        }
        if trade:
            properties["Symbol"] = self._rich_text(str(trade.get("symbol", "")))
        self._create_page(self.agent_perf_ds, properties, context="agent performance")

    def sync_risk_event(
        self,
        event_type: str,
        message: str,
        severity: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self._can_sync(self.risk_events_ds):
            return
        now = datetime.now(timezone.utc).isoformat()
        title = f"{event_type} — {severity}"
        properties: dict[str, Any] = {
            "Name": self._title(title),
            "Event Type": self._rich_text(event_type),
            "Message": self._rich_text(message),
            "Severity": self._select(severity),
            "Timestamp": self._rich_text(now),
        }
        if extra:
            properties["Details"] = self._rich_text(str(extra)[:2000])
        self._create_page(self.risk_events_ds, properties, context="risk event")

    def _create_page(self, database_id: str, properties: dict[str, Any], context: str) -> None:
        try:
            self._client.pages.create(parent={"database_id": database_id}, properties=properties)
            logger.debug("Notion sync: created %s row", context)
        except Exception as exc:
            logger.warning("Notion sync failed (%s): %s", context, exc)


def get_notion_sync() -> NotionSync:
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = NotionSync()
    return _sync_instance
