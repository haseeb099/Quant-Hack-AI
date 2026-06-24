"""Shared positions read result with trust flag."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PositionsSnapshot:
    positions: list[dict[str, Any]]
    trusted: bool
