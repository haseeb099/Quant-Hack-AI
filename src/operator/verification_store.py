"""Persisted operator verification results for competition-day automation."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_STATE_PATH = Path("data/operator_verification.json")
_lock = threading.Lock()


def _default_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "last_mode": None,
        "ready": False,
        "passed": 0,
        "total": 0,
        "checks": [],
        "session": None,
    }


def read_verification_state(path: Path | str = _STATE_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _default_state()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        base = _default_state()
        base.update({k: v for k, v in data.items() if k in base or k in data})
        return base
    except (json.JSONDecodeError, OSError):
        return _default_state()


def write_verification_state(state: dict[str, Any], path: Path | str = _STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


def record_verification(result: dict[str, Any], path: Path | str = _STATE_PATH) -> dict[str, Any]:
    payload = {
        **result,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
    }
    write_verification_state(payload, path)
    return payload
