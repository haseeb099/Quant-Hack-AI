"""Persist operator watchdog snapshots for dashboard and history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path("data/operator_snapshot.json")
HISTORY_PATH = Path("data/operator_snapshot_history.jsonl")
ALERT_DEDUPE_PATH = Path("data/operator_alert_dedupe.json")


def read_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    p = path or SNAPSHOT_PATH
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> Path:
    p = path or SNAPSHOT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    return p


def append_history(snapshot: dict[str, Any], path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    line = {**snapshot, "recorded_at": datetime.now(timezone.utc).isoformat()}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, default=str) + "\n")


def read_history(limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    p = path or HISTORY_PATH
    if not p.exists():
        return []
    lines: list[str] = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    out: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def read_alert_dedupe(path: Path | None = None) -> dict[str, str]:
    p = path or ALERT_DEDUPE_PATH
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_alert_dedupe(data: dict[str, str], path: Path | None = None) -> None:
    p = path or ALERT_DEDUPE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
