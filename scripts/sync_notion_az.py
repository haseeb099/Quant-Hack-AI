#!/usr/bin/env python3
"""Sync QuantAI A–Z operator guide to Notion Tasks DB and optional guide page."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.integrations.notion_az_sync import sync_az_to_notion
from src.integrations.notion_sync import get_notion_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync QuantAI A–Z guide to Notion")
    parser.add_argument("--steps-only", action="store_true", help="Sync Command Center steps 1–10 only")
    parser.add_argument("--az-only", action="store_true", help="Sync A–Z sections only")
    parser.add_argument("--guide-page", action="store_true", help="Also update NOTION_AZ_PAGE_ID page")
    parser.add_argument("--dry-run", action="store_true", help="Check config without writing")
    args = parser.parse_args()

    sync = get_notion_sync()
    if not sync.enabled:
        print("ERROR: Notion not configured.")
        print("Set NOTION_API_KEY and NOTION_TASKS_DS_ID in .env")
        print("Optional: NOTION_AZ_PAGE_ID for full guide page with blocks")
        return 1

    if args.dry_run:
        status = sync.get_status()
        print(json.dumps(status, indent=2))
        tasks = sync.query_tasks(limit=5)
        print(f"Sample tasks: {len(tasks)}")
        return 0

    include_steps = not args.az_only
    include_az = not args.steps_only
    include_page = args.guide_page or bool(__import__("os").getenv("NOTION_AZ_PAGE_ID"))

    result = sync_az_to_notion(
        sync,
        include_guide_page=include_page,
        include_steps=include_steps,
        include_az_tasks=include_az,
    )

    print(json.dumps(result, indent=2))

    if result.get("error"):
        return 1
    if result.get("guide_page", {}).get("error") and include_page:
        print("Note: guide page sync failed — tasks may still have updated")
    print("\nNotion A–Z sync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
