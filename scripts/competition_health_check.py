#!/usr/bin/env python3
"""One-shot competition operations health check (Bloomberg-style go/no-go)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _read_lock_pid() -> int | None:
    lock = ROOT / "data" / "engine.lock"
    if not lock.exists():
        return None
    try:
        return int(lock.read_text(encoding="utf-8").strip().split()[0])
    except (ValueError, IndexError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def main() -> int:
    from src.bridges.factory import _zmq_ports_open
    from src.engine.config import QuantAIConfig, resolve_phase
    from src.operator.preflight import run_preflight
    from src.web.runtime_state import read_state

    checks: list[tuple[str, bool, str]] = []
    state = read_state()
    engine_cfg = state.get("engine_config") or {}

    lock_pid = _read_lock_pid()
    single_engine = lock_pid is None or _pid_alive(lock_pid)
    checks.append(
        (
            "Single engine lock",
            single_engine,
            f"lock_pid={lock_pid}" if lock_pid else "no lock file",
        ),
    )

    scheduled = resolve_phase(auto=True)
    engine_phase = state.get("phase", "?")
    checks.append(
        (
            "Phase alignment",
            scheduled == engine_phase,
            f"schedule={scheduled} engine={engine_phase}",
        ),
    )

    cycle_min = engine_cfg.get("cycle_minutes")
    expected_cycle = QuantAIConfig.load(auto_phase=True).cycle_minutes()
    checks.append(
        (
            "Cycle interval",
            cycle_min == expected_cycle if cycle_min is not None else False,
            f"runtime={cycle_min} expected={expected_cycle}",
        ),
    )

    session_filter = engine_cfg.get("session_symbol_filter")
    expected_sf = QuantAIConfig.load(auto_phase=True).phase_rules.get("session_symbol_filter")
    if expected_sf is None:
        expected_sf = False
    checks.append(
        (
            "Session filter",
            session_filter is expected_sf if session_filter is not None else False,
            f"runtime={session_filter} expected={expected_sf}",
        ),
    )

    initial = (state.get("account") or {}).get("initial_equity")
    baseline = os.getenv("ROUND_EQUITY_BASELINE", "platform").lower()
    expected_initial = 1_000_000.0 if baseline == "platform" else None
    if expected_initial:
        ok = initial == expected_initial
        checks.append(("Equity baseline", ok, f"initial={initial} expected={expected_initial}"))
    else:
        checks.append(("Equity baseline", True, f"session mode initial={initial}"))

    zmq_up = _zmq_ports_open()
    bridge = engine_cfg.get("bridge", "?")
    checks.append(("ZMQ ports", zmq_up, "open" if zmq_up else "closed — use MT5 direct or restart EA"))

    stale = bool(state.get("account", {}).get("account_stale"))
    checks.append(("Account fresh", not stale, "stale" if stale else "ok"))

    mt5_ok = bool(state.get("mt5_connected"))
    checks.append(("MT5 bridge", mt5_ok, state.get("zmq_last_error") or "connected"))

    preflight = run_preflight()
    checks.append(
        (
            "Preflight",
            preflight.get("ready", False),
            f"{preflight.get('passed')}/{preflight.get('total')} passed",
        ),
    )

    print("QuantAI Competition Health Check")
    print("=" * 40)
    print(f"Time (UTC): {datetime.now(timezone.utc).isoformat()}")
    print()
    failed = 0
    for label, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {label} — {detail}")

    print()
    if failed == 0:
        print("GO — all checks passed")
        return 0
    print(f"NO-GO — {failed} check(s) failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
