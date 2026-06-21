"""Persisted counters for Notion sync observability."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_STATE_PATH = Path("data/notion_sync_state.json")
_lock = threading.Lock()


def _default_state() -> dict[str, Any]:
    return {
        "trade_journal": {"success": 0, "failure": 0, "last_at": None, "last_error": None},
        "agent_performance": {"success": 0, "failure": 0, "last_at": None, "last_error": None},
        "risk_events": {"success": 0, "failure": 0, "last_at": None, "last_error": None},
        "tasks": {"success": 0, "failure": 0, "last_at": None, "last_error": None},
    }


def read_sync_state(path: Path | str = _STATE_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _default_state()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        base = _default_state()
        for key, val in data.items():
            if key in base and isinstance(val, dict):
                base[key].update(val)
        return base
    except (json.JSONDecodeError, OSError):
        return _default_state()


def write_sync_state(state: dict[str, Any], path: Path | str = _STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)


def record_sync_result(channel: str, success: bool, error: str | None = None) -> None:
    state = read_sync_state()
    bucket = state.setdefault(channel, {"success": 0, "failure": 0, "last_at": None, "last_error": None})
    if success:
        bucket["success"] = int(bucket.get("success", 0)) + 1
        bucket["last_error"] = None
    else:
        bucket["failure"] = int(bucket.get("failure", 0)) + 1
        bucket["last_error"] = (error or "unknown")[:500]
    bucket["last_at"] = datetime.now(timezone.utc).isoformat()
    write_sync_state(state)
