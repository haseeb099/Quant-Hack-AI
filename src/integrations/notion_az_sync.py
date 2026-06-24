"""Sync QuantAI A–Z operator guide and implementation steps to Notion."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from src.integrations.notion_az_content import (
    AZ_SECTIONS,
    COMPETITION_COMPLIANCE,
    GUIDE_TITLE,
    IMPLEMENTATION_STEPS,
    INSTRUMENTS_TABLE,
    OPEN_POSITION_MONITORING,
    PROJECT_STRUCTURE,
    TRADE_LIFECYCLE,
)
from src.integrations.notion_sync import NotionSync, get_notion_sync, record_sync_result

logger = logging.getLogger(__name__)

_CHUNK = 1900


def _chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts: list[str] = []
    while text:
        parts.append(text[:_CHUNK])
        text = text[_CHUNK:]
    return parts


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


def _heading_block(text: str, level: int = 2) -> dict[str, Any]:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


def _divider_block() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _find_task_page(tasks: list[dict[str, Any]], step: str | None, title_hint: str) -> dict[str, Any] | None:
    hint = title_hint.lower()
    for task in tasks:
        if step and task.get("step") == int(step):
            return task
        if hint in (task.get("title") or "").lower():
            return task
    return None


def upsert_implementation_step(
    sync: NotionSync,
    step_label: str,
    status: str = "Done",
    notes: str = "",
    step_num: str | None = None,
    existing_tasks: list[dict[str, Any]] | None = None,
) -> str:
    """Update existing task page or create new one. Returns action: updated|created|skipped."""
    if not sync.enabled or not sync._client or not sync.tasks_ds:
        return "skipped"

    existing_tasks = existing_tasks if existing_tasks is not None else sync.query_tasks(limit=100)
    match = _find_task_page(existing_tasks, step_num, step_label)
    properties: dict[str, Any] = {
        "Name": sync._title(step_label),
        "Status": sync._select(status),
    }
    if notes:
        properties["Notes"] = sync._rich_text(notes)

    try:
        if match and match.get("id"):
            sync._client.pages.update(page_id=match["id"], properties=properties)
            record_sync_result("tasks", True)
            return "updated"
        sync._client.pages.create(
            parent={"database_id": sync.tasks_ds},
            properties=properties,
        )
        record_sync_result("tasks", True)
        return "created"
    except Exception as exc:
        logger.warning("Notion step upsert failed: %s", exc)
        record_sync_result("tasks", False, str(exc))
        return "failed"


def _build_guide_blocks() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        _heading_block(GUIDE_TITLE, 1),
        _paragraph_block(
            "Complete operator reference for QuantAI Command Center. "
            "All Steps 1–10 merged to main. Engine is autonomous after single start command."
        ),
        _divider_block(),
        _heading_block("Competition Instruments", 2),
    ]
    for chunk in _chunks(INSTRUMENTS_TABLE):
        blocks.append(_paragraph_block(chunk))
    blocks.append(_divider_block())
    blocks.append(_heading_block("Project Structure", 2))
    for chunk in _chunks(PROJECT_STRUCTURE):
        blocks.append(_paragraph_block(chunk))
    blocks.append(_divider_block())
    blocks.append(_heading_block("Trade Lifecycle — Open & Close", 2))
    for chunk in _chunks(TRADE_LIFECYCLE):
        blocks.append(_paragraph_block(chunk))
    blocks.append(_divider_block())
    blocks.append(_heading_block("Open Position Monitoring", 2))
    for chunk in _chunks(OPEN_POSITION_MONITORING):
        blocks.append(_paragraph_block(chunk))
    blocks.append(_divider_block())
    blocks.append(_heading_block("Competition Compliance (Wired)", 2))
    for chunk in _chunks(COMPETITION_COMPLIANCE):
        blocks.append(_paragraph_block(chunk))
    blocks.append(_divider_block())
    blocks.append(_heading_block("A–Z Reference", 2))
    for section in AZ_SECTIONS:
        blocks.append(_heading_block(f"{section['letter']} — {section['title']}", 3))
        for chunk in _chunks(section["body"]):
            blocks.append(_paragraph_block(chunk))
    return blocks


def sync_az_guide_page(sync: NotionSync, page_id: str | None = None) -> dict[str, Any]:
    """Create or replace content on a Notion page with the A–Z guide."""
    page_id = page_id or os.getenv("NOTION_AZ_PAGE_ID", "").strip()
    if not sync.enabled or not sync._client:
        return {"ok": False, "error": "Notion sync not enabled"}
    if not page_id:
        return {"ok": False, "error": "NOTION_AZ_PAGE_ID not set — set parent page ID in .env"}

    blocks = _build_guide_blocks()
    try:
        # Archive existing top-level blocks (best-effort)
        children = sync._client.blocks.children.list(block_id=page_id)
        for block in children.get("results", []):
            bid = block.get("id")
            if bid:
                try:
                    sync._client.blocks.delete(block_id=bid)
                except Exception:
                    pass

        # Notion allows max 100 blocks per request — batch append
        for i in range(0, len(blocks), 100):
            sync._client.blocks.children.append(
                block_id=page_id,
                children=blocks[i : i + 100],
            )
        record_sync_result("tasks", True)
        return {"ok": True, "page_id": page_id, "blocks": len(blocks)}
    except Exception as exc:
        logger.warning("Notion A–Z page sync failed: %s", exc)
        record_sync_result("tasks", False, str(exc))
        return {"ok": False, "error": str(exc)}


def sync_az_to_notion(
    sync: NotionSync | None = None,
    *,
    include_guide_page: bool = True,
    include_steps: bool = True,
    include_az_tasks: bool = True,
) -> dict[str, Any]:
    """Full A–Z sync: implementation steps + A–Z task entries + optional guide page."""
    sync = sync or get_notion_sync()
    result: dict[str, Any] = {
        "enabled": sync.enabled,
        "steps": [],
        "az_sections": [],
        "guide_page": None,
    }

    if not sync.enabled:
        result["error"] = (
            "Notion not configured. Set NOTION_API_KEY and NOTION_TASKS_DS_ID in .env"
        )
        return result

    existing = sync.query_tasks(limit=100)

    if include_steps:
        for item in IMPLEMENTATION_STEPS:
            action = upsert_implementation_step(
                sync,
                item["label"],
                status="Done",
                notes=item["notes"],
                step_num=item["step"],
                existing_tasks=existing,
            )
            result["steps"].append({"step": item["step"], "label": item["label"], "action": action})
            if action == "created":
                existing = sync.query_tasks(limit=100)

    if include_az_tasks:
        for section in AZ_SECTIONS:
            title = f"{section['letter']} — {section['title']}"
            action = upsert_implementation_step(
                sync,
                title,
                status="Done",
                notes=section["body"],
                step_num=None,
                existing_tasks=existing,
            )
            result["az_sections"].append({"letter": section["letter"], "action": action})
            if action == "created":
                existing = sync.query_tasks(limit=100)

    if include_guide_page:
        result["guide_page"] = sync_az_guide_page(sync)

    result["ok"] = True
    return result
