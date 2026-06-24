"""Competition-day operator tooling — preflight checks, runbook, and verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.operator.preflight import run_preflight

if TYPE_CHECKING:
    from src.operator.verification import (
        competition_session_phase,
        get_verification_status,
        run_verification,
    )

__all__ = [
    "run_preflight",
    "competition_session_phase",
    "get_verification_status",
    "run_verification",
]


def __getattr__(name: str):
    if name in ("competition_session_phase", "get_verification_status", "run_verification"):
        from src.operator.verification import (
            competition_session_phase,
            get_verification_status,
            run_verification,
        )

        return {
            "competition_session_phase": competition_session_phase,
            "get_verification_status": get_verification_status,
            "run_verification": run_verification,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
