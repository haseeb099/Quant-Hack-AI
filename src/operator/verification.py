"""Competition-day automated verification — pytest, preflight, copilot, launch readiness."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.operator.preflight import run_preflight
from src.operator.verification_store import read_verification_state, record_verification
from src.web.between_round import is_scheduled_adaptation_window
from src.web.launch_readiness import COMPETITION_LAUNCH_UTC, evaluate_launch_readiness
from src.web.runtime_state import read_state

_BST = ZoneInfo("Europe/London")

_QUICK_PYTEST = [
    "tests/test_operator_api.py",
    "tests/test_launch_readiness.py",
    "tests/test_pre_trade_gate.py",
    "tests/test_copilot_api.py",
    "tests/test_dashboard_api.py",
]


def _check(code: str, label: str, passed: bool, detail: str = "", remediation: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "passed": passed,
        "detail": detail,
        "remediation": remediation,
    }


def competition_session_phase(now: datetime | None = None) -> dict[str, Any]:
    """Return current competition-day phase relative to Round 1 launch (BST)."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(_BST)
    launch_local = COMPETITION_LAUNCH_UTC.astimezone(_BST)
    pre_session = launch_local.replace(hour=21, minute=30, second=0, microsecond=0)
    if local.date() != launch_local.date():
        if is_scheduled_adaptation_window(now):
            phase = "between_rounds"
            label = "Between rounds (22:00–23:00 BST)"
        elif local > launch_local:
            phase = "during_round"
            label = "During competition round"
        else:
            phase = "pre_competition"
            label = "Pre-competition"
    elif local < pre_session:
        phase = "pre_session"
        label = "Pre-session (before 21:30 BST)"
    elif local < launch_local:
        phase = "pre_launch"
        label = "Pre-launch (21:30–22:00 BST)"
    elif is_scheduled_adaptation_window(now):
        phase = "between_rounds"
        label = "Between rounds (22:00–23:00 BST)"
    else:
        phase = "during_round"
        label = "During round (24h live)"

    seconds_to_launch = max(0, int((COMPETITION_LAUNCH_UTC - now).total_seconds()))
    return {
        "phase": phase,
        "label": label,
        "local_time_bst": local.isoformat(),
        "launch_at_bst": launch_local.isoformat(),
        "seconds_to_launch": seconds_to_launch,
        "launched": now >= COMPETITION_LAUNCH_UTC,
    }


def _run_pytest(quick: bool = True) -> dict[str, Any]:
    root = Path(".").resolve()
    targets = _QUICK_PYTEST if quick else ["tests/"]
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=line"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300 if quick else 600,
            check=False,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        tail = "\n".join(output.strip().splitlines()[-5:])
        passed = proc.returncode == 0
        summary = tail.splitlines()[-1] if tail else f"exit={proc.returncode}"
        return _check(
            "PYTEST",
            "Pytest suite" + (" (quick)" if quick else " (full)"),
            passed,
            summary,
            "Fix failing tests before competition launch" if not passed else "",
        )
    except subprocess.TimeoutExpired:
        return _check("PYTEST", "Pytest suite", False, "Timed out", "Re-run with quick=true or investigate hangs")
    except OSError as exc:
        return _check("PYTEST", "Pytest suite", False, str(exc))


def _check_copilot() -> dict[str, Any]:
    try:
        from src.copilot.analyzer import CopilotAnalyzer

        analyzer = CopilotAnalyzer()
        result = analyzer.analyze_symbol(
            symbol="EUR/USD",
            volume=0.01,
            direction="BUY",
            state=read_state(),
            use_llm=False,
        )
        ok = result.verdict in ("ALLOW", "WAIT", "BLOCK", "REFUSE")
        return _check(
            "COPILOT",
            "Copilot grounded analysis",
            ok,
            f"verdict={result.verdict}",
            "Check copilot context and runtime state" if not ok else "",
        )
    except Exception as exc:
        return _check("COPILOT", "Copilot grounded analysis", False, str(exc))


def _check_learning_pipeline() -> dict[str, Any]:
    script = Path("scripts/run_learning_pipeline.sh")
    adapt = Path("scripts/adapt_round.py")
    ok = script.is_file() and adapt.is_file()
    return _check(
        "LEARNING_PIPELINE",
        "Learning pipeline scripts",
        ok,
        "adapt_round + run_learning_pipeline present" if ok else "missing scripts",
        "Ensure scripts/run_learning_pipeline.sh exists" if not ok else "",
    )


def run_verification(*, quick: bool = True, persist: bool = True) -> dict[str, Any]:
    """Run automated competition-day verification suite."""
    state = read_state()
    session = competition_session_phase()
    checks: list[dict[str, Any]] = [
        _run_pytest(quick=quick),
        _check_copilot(),
        _check_learning_pipeline(),
    ]

    preflight = run_preflight(zmq_only=True)
    checks.append(_check(
        "PREFLIGHT",
        "Preflight checks",
        preflight.get("ready", False),
        f"{preflight.get('passed', 0)}/{preflight.get('total', 0)} passed",
        "Run scripts/preflight_competition.py --zmq-only",
    ))

    launch = evaluate_launch_readiness(state)
    checks.append(_check(
        "LAUNCH_READINESS",
        "Launch readiness",
        launch.get("ready", False),
        str(launch.get("summary", {})),
        "Resolve launch readiness failures on Overview",
    ))

    passed = sum(1 for c in checks if c["passed"])
    result = {
        "ready": passed == len(checks),
        "passed": passed,
        "total": len(checks),
        "mode": "quick" if quick else "full",
        "checks": checks,
        "session": session,
        "preflight": preflight,
        "launch_readiness": launch.get("ready"),
    }
    if persist:
        record_verification(result)
    return result


def get_verification_status() -> dict[str, Any]:
    """Return last verification run plus live session phase."""
    cached = read_verification_state()
    session = competition_session_phase()
    return {
        **cached,
        "session": session,
        "has_run": bool(cached.get("last_run_at")),
    }
