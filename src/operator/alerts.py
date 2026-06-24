"""Operator alert dispatch — log file, Logfire, webhook, and Notion."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from src.operator.snapshot_store import read_alert_dedupe, write_alert_dedupe

logger = logging.getLogger(__name__)

ALERT_LOG_PATH = Path("logs/operator_alerts.log")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _status_rank(status: str) -> int:
    return {"GREEN": 1, "YELLOW": 2, "RED": 3, "UNKNOWN": 0}.get(status.upper(), 0)


def alert_min_status() -> str:
    return os.getenv("OPERATOR_ALERT_MIN_STATUS", "YELLOW").strip().upper()


def should_alert(status: str) -> bool:
    return _status_rank(status) >= _status_rank(alert_min_status())


def alert_fingerprint(snapshot: dict[str, Any]) -> str:
    codes: list[str] = []
    for section in ("reconciliation", "risk_compliance", "mt5_checks"):
        block = snapshot.get(section) or {}
        for issue in block.get("issues", []):
            if not issue.get("passed", True) and issue.get("severity") in ("CRITICAL", "WARNING"):
                codes.append(str(issue.get("code", "")))
        for check in block.get("checks", []):
            if not check.get("passed", True):
                codes.append(str(check.get("code", "")))
    if snapshot.get("mt5_log", {}).get("status") == "RED":
        codes.append("MT5_LOG_ERRORS")
    return "|".join(sorted(set(codes))) or str(snapshot.get("status", "RED"))


def format_alert_message(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary", {})
    failed_checks: list[str] = []
    for section in ("reconciliation", "risk_compliance"):
        block = snapshot.get(section) or {}
        for issue in block.get("issues", []):
            if not issue.get("passed", True):
                failed_checks.append(f"{issue.get('code')}: {issue.get('detail')}")
    for check in (snapshot.get("mt5_checks") or {}).get("checks", []):
        if not check.get("passed", True):
            failed_checks.append(f"{check.get('code')}: {check.get('detail')}")

    lines = [
        f"Operator watchdog {snapshot.get('status')} at {snapshot.get('timestamp')}",
        f"Reconciliation: {(snapshot.get('reconciliation') or {}).get('status')}",
        f"Risk: {(snapshot.get('risk_compliance') or {}).get('status')}",
        f"MT5 ready: {(snapshot.get('mt5_checks') or {}).get('ready')}",
        (
            f"Positions mt5={summary.get('mt5_position_count')} "
            f"engine={summary.get('engine_position_count')}"
        ),
    ]
    if failed_checks:
        lines.append("Issues:")
        lines.extend(f"  - {item}" for item in failed_checks[:8])
    return "\n".join(lines)


def _dedupe_key(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status", "UNKNOWN"))
    return f"{status}:{alert_fingerprint(snapshot)}"


def _is_deduped(snapshot: dict[str, Any], dedupe_minutes: int) -> bool:
    dedupe = read_alert_dedupe()
    key = _dedupe_key(snapshot)
    last_sent_raw = dedupe.get(key)
    if not last_sent_raw:
        return False
    try:
        last_sent = datetime.fromisoformat(last_sent_raw.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - last_sent < timedelta(minutes=dedupe_minutes)
    except ValueError:
        return False


def _mark_deduped(snapshot: dict[str, Any]) -> None:
    dedupe = read_alert_dedupe()
    dedupe[_dedupe_key(snapshot)] = datetime.now(timezone.utc).isoformat()
    write_alert_dedupe(dedupe)


def _write_log_file(snapshot: dict[str, Any], message: str) -> bool:
    try:
        ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": snapshot.get("status"),
            "fingerprint": alert_fingerprint(snapshot),
            "message": message,
            "summary": snapshot.get("summary", {}),
        }
        with open(ALERT_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        logger.warning("Operator alert logged to %s — status=%s", ALERT_LOG_PATH, snapshot.get("status"))
        return True
    except OSError as exc:
        logger.error("Failed to write operator alert log: %s", exc)
        return False


def _emit_logfire(snapshot: dict[str, Any], message: str) -> bool:
    try:
        from src.utils.logger import is_logfire_active

        if not is_logfire_active():
            return False
        import logfire

        status = str(snapshot.get("status", "UNKNOWN")).upper()
        fields = {
            "status": status,
            "fingerprint": alert_fingerprint(snapshot),
            "message": message,
            "reconciliation_status": (snapshot.get("reconciliation") or {}).get("status"),
            "risk_status": (snapshot.get("risk_compliance") or {}).get("status"),
            "mt5_ready": (snapshot.get("mt5_checks") or {}).get("ready"),
            **(snapshot.get("summary") or {}),
        }
        if status == "RED":
            logfire.error("operator_watchdog_alert", **fields)
        else:
            logfire.warning("operator_watchdog_alert", **fields)
        return True
    except Exception:
        logger.debug("Logfire operator alert failed", exc_info=True)
        return False


def _send_webhook(snapshot: dict[str, Any], message: str) -> bool:
    url = os.getenv("OPERATOR_ALERT_WEBHOOK", "").strip()
    if not url:
        return False
    payload = {
        "text": message,
        "status": snapshot.get("status"),
        "timestamp": snapshot.get("timestamp"),
        "fingerprint": alert_fingerprint(snapshot),
        "summary": snapshot.get("summary", {}),
    }
    try:
        response = httpx.post(url, json=payload, timeout=15.0)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Operator webhook alert failed: %s", exc)
        return False


def maybe_send_notion_alert(snapshot: dict[str, Any], dedupe_minutes: int = 30) -> bool:
    enabled = _env_bool("OPERATOR_ALERT_NOTION")
    if not enabled or snapshot.get("status") != "RED":
        return False

    fingerprint = alert_fingerprint(snapshot)
    dedupe = read_alert_dedupe()
    now = datetime.now(timezone.utc)
    notion_key = f"notion:{fingerprint}"
    last_sent_raw = dedupe.get(notion_key)
    if last_sent_raw:
        try:
            last_sent = datetime.fromisoformat(last_sent_raw.replace("Z", "+00:00"))
            if now - last_sent < timedelta(minutes=dedupe_minutes):
                return False
        except ValueError:
            pass

    from src.integrations.notion_sync import get_notion_sync

    sync = get_notion_sync()
    message = format_alert_message(snapshot)
    sent = sync.sync_implementation_step(
        step_label=f"Operator watchdog RED — {fingerprint[:80]}",
        status="To Do",
        notes=message,
    )
    if sent:
        dedupe[notion_key] = now.isoformat()
        write_alert_dedupe(dedupe)
    return sent


def dispatch_discipline_warning(
    discipline_score: int,
    halt_threshold: int = 95,
    warn_at: int = 97,
) -> dict[str, Any]:
    """Warn when discipline score approaches finals halt threshold."""
    if halt_threshold is None or discipline_score > warn_at:
        return {"dispatched": False, "reason": "above_warn_threshold"}
    if discipline_score <= halt_threshold:
        return {"dispatched": False, "reason": "already_at_halt"}
    message = (
        f"Discipline score {discipline_score} — within {warn_at - discipline_score} points "
        f"of halt threshold {halt_threshold}. Review risk before new entries."
    )
    logger.warning(message)
    try:
        ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "YELLOW",
            "fingerprint": "DISCIPLINE_WARNING",
            "message": message,
            "discipline_score": discipline_score,
            "halt_threshold": halt_threshold,
        }
        with open(ALERT_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        return {"dispatched": True, "message": message}
    except OSError as exc:
        logger.error("Failed to write discipline warning: %s", exc)
        return {"dispatched": False, "reason": str(exc)}


def dispatch_operator_alerts(
    snapshot: dict[str, Any],
    *,
    enable_notion: bool | None = None,
) -> dict[str, Any]:
    """Dispatch operator alerts when status meets OPERATOR_ALERT_MIN_STATUS."""
    status = str(snapshot.get("status", "UNKNOWN")).upper()
    if not should_alert(status):
        return {"dispatched": False, "reason": "below_threshold", "status": status}

    dedupe_minutes = int(os.getenv("OPERATOR_ALERT_DEDUPE_MINUTES", "15"))
    if _is_deduped(snapshot, dedupe_minutes):
        return {"dispatched": False, "reason": "deduped", "status": status}

    message = format_alert_message(snapshot)
    channels: dict[str, bool] = {}

    if _env_bool("OPERATOR_ALERT_LOG", True):
        channels["log_file"] = _write_log_file(snapshot, message)
    if _env_bool("OPERATOR_ALERT_LOGFIRE", True):
        channels["logfire"] = _emit_logfire(snapshot, message)
    if os.getenv("OPERATOR_ALERT_WEBHOOK", "").strip():
        channels["webhook"] = _send_webhook(snapshot, message)
    if enable_notion if enable_notion is not None else _env_bool("OPERATOR_ALERT_NOTION"):
        channels["notion"] = maybe_send_notion_alert(snapshot)

    _mark_deduped(snapshot)
    logger.info(
        "Operator alerts dispatched — status=%s channels=%s",
        status,
        {name: sent for name, sent in channels.items() if sent},
    )
    return {"dispatched": True, "status": status, "channels": channels}
