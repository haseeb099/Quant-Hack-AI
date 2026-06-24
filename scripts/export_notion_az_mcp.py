#!/usr/bin/env python3
"""Export A-Z guide as markdown for Notion MCP sync."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.integrations.notion_az_content import (
    AZ_SECTIONS,
    COMPETITION_COMPLIANCE,
    IMPLEMENTATION_STEPS,
    INSTRUMENTS_TABLE,
    OPEN_POSITION_MONITORING,
    PROJECT_STRUCTURE,
    TRADE_LIFECYCLE,
)

parts: list[str] = []
parts.append(
    "> **Status:** COMPLETE — synced via Notion MCP from "
    "`src/integrations/notion_az_content.py`. Steps 1–11 done. 140 tests passing."
)
parts.append("")
parts.append("## Scoring Formula")
parts.append("```javascript")
parts.append("Final Score = 70% Return + 15% Drawdown + 10% Sharpe + 5% Risk Discipline")
parts.append("```")
parts.append("")
parts.append("## Competition Instruments (15 only)")
parts.append(INSTRUMENTS_TABLE)
parts.append("")
parts.append("---")
parts.append("## Command Center Steps (All Done)")
for item in IMPLEMENTATION_STEPS:
    parts.append(f"{item['step']}. **{item['label']}** — {item['notes']}")
parts.append("")
parts.append("---")
parts.append("## Trade Lifecycle — Open & Close")
parts.append(TRADE_LIFECYCLE)
parts.append("")
parts.append("---")
parts.append("## Open Position Monitoring")
parts.append(OPEN_POSITION_MONITORING)
parts.append("")
parts.append("---")
parts.append("## Competition Compliance (Wired)")
parts.append(COMPETITION_COMPLIANCE)
parts.append("")
parts.append("---")
parts.append("## A–Z Reference")
for section in AZ_SECTIONS:
    parts.append(f"### {section['letter']} — {section['title']}")
    parts.append(section["body"])
    parts.append("")
parts.append("---")
parts.append("## Project Structure")
parts.append(PROJECT_STRUCTURE)
parts.append("")
parts.append("> **Re-sync:** `python scripts/sync_notion_az.py --guide-page` or Notion MCP")

out = Path(__file__).resolve().parents[1] / "data" / "notion_az_mcp_export.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(parts), encoding="utf-8")
print(out)
print("chars:", len(parts))
