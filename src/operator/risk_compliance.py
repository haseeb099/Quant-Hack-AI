"""Read-only risk compliance checks against config/risk.yaml and runtime state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from src.engine.config import QuantAIConfig


def _issue(
    code: str,
    label: str,
    severity: str,
    passed: bool,
    detail: str = "",
    remediation: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "passed": passed,
        "detail": detail,
        "remediation": remediation,
    }


def _load_risk_config(path: Path | str = Path("config/risk.yaml")) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("risk", data)


def _upcoming_high_impact(calendar_events: list[dict[str, Any]], hours: int = 4) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours)
    upcoming: list[dict[str, Any]] = []
    for event in calendar_events:
        impact = str(event.get("impact", event.get("importance", ""))).lower()
        if impact not in ("high", "3", "red"):
            continue
        ts_raw = event.get("time") or event.get("timestamp") or event.get("date")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= ts <= horizon:
            upcoming.append(event)
    return upcoming


def check_risk_compliance(
    *,
    state: dict[str, Any] | None = None,
    risk_config: dict[str, Any] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    """Evaluate drawdown headroom, margin, leverage, concentration, and event gate."""
    from src.web.runtime_state import read_state

    state = state or read_state()
    risk_config = risk_config or _load_risk_config()
    risk = state.get("risk", {})
    account = state.get("account", {})
    calendar_events = calendar_events or []

    issues: list[dict[str, Any]] = []
    dd_tier = str(risk.get("dd_tier", "normal"))
    drawdown_pct = float(risk.get("drawdown_pct", 0) or 0)
    dd_cfg = risk_config.get("drawdown", {})
    warning_max = float(dd_cfg.get("warning_max", 0.12))
    critical_max = float(dd_cfg.get("critical_max", 0.14))
    headroom_to_warning = max(0.0, warning_max - drawdown_pct)
    issues.append(
        _issue(
            "DRAWDOWN_HEADROOM",
            "Drawdown tier headroom",
            "WARNING" if dd_tier in ("warning", "critical", "emergency") else "INFO",
            dd_tier in ("normal", "elevated"),
            f"tier={dd_tier} dd={drawdown_pct:.2%} headroom_to_warning={headroom_to_warning:.2%}",
            "Reduce exposure before warning tier; never override risk.yaml automatically",
        ),
    )

    margin_state = risk.get("margin_state", {})
    if isinstance(margin_state, str):
        margin_level = None
        margin_action = margin_state
    else:
        margin_level = margin_state.get("margin_level_pct")
        margin_action = margin_state.get("action", "normal")
    stop_out = float(risk_config.get("margin", {}).get("stop_out_level_pct", 30))
    margin_ok = margin_level is None or float(margin_level) > stop_out + 5
    issues.append(
        _issue(
            "MARGIN_LEVEL",
            "Margin level vs stop-out",
            "CRITICAL" if margin_level is not None and float(margin_level) <= stop_out else "WARNING",
            margin_ok,
            f"level={margin_level}% action={margin_action} stop_out={stop_out}%",
            "Reduce gross exposure; margin watcher should auto-deleverage",
        ),
    )

    effective_leverage = float(risk.get("effective_leverage", 0) or 0)
    lev_max = float(risk_config.get("leverage", {}).get("max", 20))
    lev_hard = float(risk_config.get("leverage", {}).get("hard_stop", 25))
    lev_ok = effective_leverage <= lev_max or effective_leverage == 0
    issues.append(
        _issue(
            "LEVERAGE",
            "Effective leverage cap",
            "WARNING" if effective_leverage > lev_hard else "INFO",
            lev_ok,
            f"effective={effective_leverage:.1f}x max={lev_max}x hard={lev_hard}x",
            "Close or reduce largest positions to restore leverage discipline",
        ),
    )

    concentration = float(risk.get("concentration_pct", 0) or 0)
    conc_max = float(risk_config.get("concentration", {}).get("max_pct", 0.40))
    conc_ok = concentration <= conc_max or concentration == 0
    issues.append(
        _issue(
            "CONCENTRATION",
            "Portfolio concentration",
            "WARNING",
            conc_ok,
            f"concentration={concentration:.1%} max={conc_max:.0%}",
            "Diversify or trim largest symbol exposure",
        ),
    )

    equity = float(account.get("equity", 0) or 0)
    balance = float(account.get("balance", equity) or equity)
    daily_loss_limit = float(dd_cfg.get("daily_loss_limit", 0.05))
    if equity > 0 and balance > 0:
        daily_loss = max(0.0, (balance - equity) / balance)
        daily_ok = daily_loss < daily_loss_limit
    else:
        daily_loss = 0.0
        daily_ok = True
    issues.append(
        _issue(
            "DAILY_LOSS",
            "Daily loss limit",
            "WARNING",
            daily_ok,
            f"daily_loss={daily_loss:.2%} limit={daily_loss_limit:.0%}",
            "Pause new entries if daily loss approaches constitution limit",
        ),
    )

    upcoming = _upcoming_high_impact(calendar_events)
    issues.append(
        _issue(
            "EVENT_GATE",
            "Upcoming high-impact events",
            "INFO" if upcoming else "INFO",
            True,
            f"{len(upcoming)} high-impact within 4h" if upcoming else "none within 4h",
            "Event gate may block entries — review /api/intelligence/calendar",
        ),
    )

    phase_name = phase or state.get("phase", "round1")
    try:
        config = QuantAIConfig.load(phase=phase_name)
        phase_rules = config.phase_rules
        phase_detail = (
            f"phase={phase_name} risk_mult={phase_rules.get('risk_multiplier')} "
            f"max_entries={phase_rules.get('max_new_entries_per_cycle')}"
        )
        phase_ok = bool(phase_rules)
    except Exception as exc:
        phase_ok = False
        phase_detail = str(exc)
    issues.append(
        _issue(
            "PHASE_BEHAVIOR",
            "Phase behavior flags",
            "INFO",
            phase_ok,
            phase_detail,
            "Verify QUANTAI_PHASE matches competition round",
        ),
    )

    failed = [i for i in issues if not i.get("passed", True)]
    if any(i.get("severity") == "CRITICAL" for i in failed):
        status = "RED"
    elif any(i.get("severity") == "WARNING" for i in failed):
        status = "YELLOW"
    elif failed:
        status = "YELLOW"
    else:
        status = "GREEN"

    return {
        "status": status,
        "issues": issues,
        "upcoming_events": upcoming[:5],
    }
