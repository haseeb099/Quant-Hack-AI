"""QuantAI web dashboard API package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.web.app import create_app, run_dashboard

__all__ = ["create_app", "run_dashboard"]


def __getattr__(name: str):
    if name in __all__:
        from src.web.app import create_app, run_dashboard

        return {"create_app": create_app, "run_dashboard": run_dashboard}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
