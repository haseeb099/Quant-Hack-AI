"""Shared formatting helpers for operator-facing summaries."""

from __future__ import annotations

from typing import Any


def format_launch_summary(summary: dict[str, Any] | None) -> str:
    """Human-readable launch readiness summary line."""
    if not summary:
        return "0 pass · 0 warn · 0 fail · 0 skip"
    return (
        f"{summary.get('pass', 0)} pass · "
        f"{summary.get('warn', 0)} warn · "
        f"{summary.get('fail', 0)} fail · "
        f"{summary.get('skip', 0)} skip"
    )
