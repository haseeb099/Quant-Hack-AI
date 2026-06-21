"""Integration status endpoints (Notion, Logfire)."""

from __future__ import annotations

import os

from fastapi import APIRouter

from src.integrations.notion_sync import notion_sync_enabled

router = APIRouter(tags=["integrations"])


@router.get("/api/integrations")
def get_integrations() -> dict:
    notion_key = bool(os.getenv("NOTION_API_KEY", "").strip())
    logfire = bool(os.getenv("LOGFIRE_TOKEN", "").strip())
    return {
        "notion": {
            "enabled": notion_sync_enabled(),
            "configured": notion_key,
            "trade_journal_ds": bool(os.getenv("NOTION_TRADE_JOURNAL_DS_ID")),
            "agent_perf_ds": bool(os.getenv("NOTION_AGENT_PERF_DS_ID")),
            "risk_events_ds": bool(os.getenv("NOTION_RISK_EVENTS_DS_ID")),
        },
        "logfire": {
            "enabled": logfire,
            "configured": logfire,
        },
        "dashboard_auth": bool(os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()),
    }
