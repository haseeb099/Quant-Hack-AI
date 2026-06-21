"""Notion integration API — status, tasks, step sync."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.integrations.notion_sync import get_notion_sync, notion_sync_enabled
from src.integrations.notion_az_sync import sync_az_to_notion
from src.utils.logger import instrument_span, log_event

router = APIRouter(tags=["notion"])


class NotionStepSyncRequest(BaseModel):
    step_label: str = Field(min_length=3, max_length=200)
    status: str = Field(default="Done", max_length=50)
    notes: str = Field(default="", max_length=2000)


@router.get("/api/notion/status")
@instrument_span("quantai.notion.status")
def get_notion_status() -> dict:
    sync = get_notion_sync()
    status = sync.get_status()
    status["notion_sync_enabled"] = notion_sync_enabled()
    return status


@router.get("/api/notion/tasks")
@instrument_span("quantai.notion.tasks")
def get_notion_tasks(limit: int = 30) -> dict:
    sync = get_notion_sync()
    if not sync.enabled:
        return {"tasks": [], "enabled": False, "message": "Notion sync not configured"}
    tasks = sync.query_tasks(limit=limit)
    return {"tasks": tasks, "enabled": True, "count": len(tasks)}


@router.post("/api/notion/sync/step")
@instrument_span("quantai.notion.sync_step")
def sync_notion_step(body: NotionStepSyncRequest) -> dict:
    sync = get_notion_sync()
    if not sync.enabled or not sync.tasks_ds:
        raise HTTPException(status_code=503, detail="Notion Tasks database not configured")
    ok = sync.sync_implementation_step(body.step_label, body.status, body.notes)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to sync step to Notion")
    log_event("notion_step_sync", step=body.step_label, status=body.status)
    return {"ok": True, "step": body.step_label, "status": body.status}


@router.post("/api/notion/sync/az")
@instrument_span("quantai.notion.sync_az")
def sync_notion_az() -> dict:
    """Sync A–Z operator guide + Steps 1–10 to Notion Tasks DB."""
    sync = get_notion_sync()
    if not sync.enabled or not sync.tasks_ds:
        raise HTTPException(status_code=503, detail="Notion Tasks database not configured")
    result = sync_az_to_notion(sync, include_guide_page=True)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    log_event("notion_az_sync", steps=len(result.get("steps", [])))
    return {"ok": True, **result}
