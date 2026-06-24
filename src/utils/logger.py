"""Structured logging with Logfire integration."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

_logfire_configured = False


def is_logfire_active() -> bool:
    return _logfire_configured


def setup_logging(level: str = "INFO", enable_logfire: bool = True) -> None:
    """Configure console logging and optional Logfire instrumentation."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    global _logfire_configured
    if enable_logfire and os.getenv("LOGFIRE_TOKEN") and not _logfire_configured:
        try:
            import logfire

            logfire.configure()
            logfire.install_auto_tracing(
                modules=["src"],
                min_duration=0.01,
                check_imported_modules="warn",
            )
            _logfire_configured = True
            logging.getLogger(__name__).info("Logfire observability enabled")
        except ImportError:
            logging.getLogger(__name__).warning("logfire not installed — console logging only")
    elif enable_logfire and not os.getenv("LOGFIRE_TOKEN"):
        logging.getLogger(__name__).info("LOGFIRE_TOKEN not set — console logging only")


def log_event(name: str, **fields: Any) -> None:
    """Structured Logfire event — no-op when Logfire is unavailable."""
    if not _logfire_configured:
        return
    try:
        import logfire

        logfire.info(name, **fields)
    except Exception:
        pass


def instrument_span(name: str):
    """Decorator for Logfire spans — falls back to no-op if unavailable."""
    try:
        import logfire
        return logfire.instrument(name)
    except ImportError:
        def noop(func):
            return func
        return noop


def log_trade_decision(logger: logging.Logger, decision: Any, features: Any) -> None:
    """Log a structured trade decision for observability."""
    logger.info(
        "DECISION symbol=%s direction=%s confidence=%.2f regime=%s",
        getattr(decision, "symbol", "?"),
        getattr(decision.direction, "value", getattr(decision, "direction", "?")),
        getattr(decision, "confidence", 0),
        getattr(getattr(features, "regime", None), "value", getattr(features, "regime", "?")),
    )

    if _logfire_configured:
        try:
            import logfire
            logfire.info(
                "trade_decision",
                symbol=getattr(decision, "symbol", "?"),
                direction=str(getattr(decision.direction, "value", decision.direction)),
                confidence=getattr(decision, "confidence", 0),
                regime=str(getattr(getattr(features, "regime", None), "value", "?")),
                used_ai=getattr(decision, "used_ai", False),
                skip_reason=getattr(decision, "skip_reason", None),
                status=getattr(decision, "status", None),
            )
        except Exception:
            pass
