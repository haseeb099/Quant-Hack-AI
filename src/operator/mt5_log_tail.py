"""Tail MetaTrader 5 Expert Advisor logs for DWX bridge errors."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_EA_MARKERS = ("DWX_ZeroMQ_Server", "ZeroMQ", "zmq")
_ERROR_MARKERS = ("error", "failed", "exception", "invalid", "reject", "timeout", "disconnect")


def find_mt5_log_dir() -> Path | None:
    """Locate the newest MT5 terminal MQL5/Logs directory."""
    candidates: list[Path] = []
    appdata = os.getenv("APPDATA")
    if appdata:
        terminal_root = Path(appdata) / "MetaQuotes" / "Terminal"
        if terminal_root.exists():
            for terminal_dir in terminal_root.iterdir():
                logs = terminal_dir / "MQL5" / "Logs"
                if logs.is_dir():
                    candidates.append(logs)

    mt5_path = os.getenv("MT5_PATH", "").strip().strip('"')
    if mt5_path:
        install = Path(mt5_path).parent
        for rel in (Path("MQL5") / "Logs", Path("logs")):
            logs = install / rel
            if logs.is_dir():
                candidates.append(logs)

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_log_timestamp(line: str, fallback_date: datetime) -> datetime | None:
    match = re.match(r"^(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y.%m.%d %H:%M:%S").replace(
            tzinfo=timezone.utc,
        )
    except ValueError:
        return fallback_date


def tail_dwx_errors(
    *,
    log_dir: Path | str | None = None,
    max_lines: int = 100,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """Scan recent MT5 log files for DWX/ZeroMQ error lines."""
    directory = Path(log_dir) if log_dir else find_mt5_log_dir()
    if directory is None or not directory.exists():
        return {
            "available": False,
            "log_dir": None,
            "errors": [],
            "error_count": 0,
            "status": "UNKNOWN",
            "detail": "MT5 log directory not found",
        }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    log_files = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        return {
            "available": True,
            "log_dir": str(directory),
            "errors": [],
            "error_count": 0,
            "status": "GREEN",
            "detail": "No log files present",
        }

    errors: list[dict[str, Any]] = []
    for log_file in log_files[:3]:
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        fallback_date = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
        for line in lines[-max_lines:]:
            lower = line.lower()
            if not any(marker.lower() in lower for marker in _EA_MARKERS):
                continue
            if not any(marker in lower for marker in _ERROR_MARKERS):
                continue
            ts = _parse_log_timestamp(line, fallback_date)
            if ts and ts < cutoff:
                continue
            errors.append(
                {
                    "timestamp": ts.isoformat() if ts else None,
                    "line": line[:500],
                    "file": log_file.name,
                },
            )

    errors = errors[-max_lines:]
    status = "RED" if errors else "GREEN"
    return {
        "available": True,
        "log_dir": str(directory),
        "errors": errors,
        "error_count": len(errors),
        "status": status,
        "detail": f"{len(errors)} DWX error lines in last {lookback_hours}h",
    }
