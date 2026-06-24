"""Structured pre-competition checks — shared by CLI and dashboard API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

COMPETITION_SYMBOLS = [
    "AUD/USD", "EUR/CHF", "EUR/GBP", "EUR/USD", "GBP/USD",
    "USD/CAD", "USD/CHF", "USD/JPY", "XAG/USD", "XAU/USD",
    "BAR/USD", "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
]


def _result(code: str, label: str, passed: bool, detail: str = "", remediation: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "passed": passed,
        "detail": detail,
        "remediation": remediation,
    }


def check_account_profile() -> dict[str, Any]:
    from src.risk.account_profile import detect_profile

    override = os.getenv("ACCOUNT_PROFILE", "auto")
    equity = float(os.getenv("PREFLIGHT_EQUITY", "1000000"))
    profile = detect_profile(equity, override)
    ok = profile.name in ("competition", "practice", "micro")
    return _result(
        "ACCOUNT_PROFILE",
        "Account profile",
        ok,
        f"{profile.name} (equity={equity:,.0f})",
    )


def check_config_symbols() -> dict[str, Any]:
    from src.engine.config import QuantAIConfig

    config = QuantAIConfig.load(phase="round1")
    active = set(config.active_symbols)
    expected = set(COMPETITION_SYMBOLS)
    missing = expected - active
    extra = active - expected
    ok = not missing and not extra
    detail = "all 15 symbols" if ok else f"missing={missing} extra={extra}"
    return _result("INSTRUMENTS", "Instrument universe", ok, detail)


def check_risk_self_test() -> dict[str, Any]:
    from src.risk.drawdown_guard import DrawdownGuard
    from src.risk.margin_monitor import MarginMonitor

    dd = DrawdownGuard({
        "normal_max": 0.05,
        "elevated_max": 0.10,
        "warning_max": 0.12,
        "critical_max": 0.12,
        "emergency_close": 0.15,
        "size_multipliers": {"normal": 1.0, "critical": 0.25, "emergency": 0.0},
    })
    dd.reset(1_000_000)
    critical = dd.update(870_000)
    emergency = dd.update(840_000)
    margin = MarginMonitor({}, {"max": 20, "warning": 15, "hard_stop": 25}, {"max_pct": 0.40, "hard_stop_pct": 0.50})
    state = margin.check(1_000_000, 850_000, 22_000_000, 0.45)
    ok = critical.tier == "critical" and emergency.tier == "emergency" and state.block_new_trades
    return _result(
        "RISK_SELF_TEST",
        "Risk cap self-test",
        ok,
        f"dd={critical.tier}->{emergency.tier} margin={state.action}",
    )


def check_dashboard_auth() -> dict[str, Any]:
    token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if not token:
        return _result(
            "DASHBOARD_AUTH",
            "Dashboard auth",
            True,
            "optional — no token set",
            "Set DASHBOARD_AUTH_TOKEN for Northflank public ingress",
        )
    return _result("DASHBOARD_AUTH", "Dashboard auth", True, "token configured")


def check_tick_stream(zmq_only: bool = False) -> dict[str, Any]:
    if zmq_only:
        from src.bridges.zeromq_connector import ZeroMQConnector

        conn = ZeroMQConnector()
        if not conn.connect():
            return _result(
                "TICK_STREAM",
                "Tick stream (ZMQ)",
                False,
                "bridge not connected",
                "Start DWX_ZeroMQ_Server in MT5; run scripts/zmq_diagnose.py",
            )
        tick = conn.poll_ticks()
        conn.close()
        return _result("TICK_STREAM", "Tick stream (ZMQ)", tick is not None, "received tick" if tick else "no tick yet")

    try:
        from src.data.live_feed import LiveFeed
        from src.bridges.zeromq_connector import ZeroMQConnector

        conn = ZeroMQConnector()
        if not conn.connect():
            return _result("TICK_STREAM", "Tick stream", False, "ZMQ not connected")
        feed = LiveFeed(conn, COMPETITION_SYMBOLS)
        feed.start()
        import time
        time.sleep(2)
        healthy = getattr(feed, "is_healthy", lambda: False)()
        feed.stop()
        conn.close()
        return _result("TICK_STREAM", "Tick stream (LiveFeed)", healthy, "healthy" if healthy else "no fresh ticks")
    except ImportError:
        return _result("TICK_STREAM", "Tick stream", True, "LiveFeed optional — skipped")


def check_engine_sim_cycle() -> dict[str, Any]:
    from src.engine.config import QuantAIConfig
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    engine.start()
    engine.run_cycle()
    return _result("ENGINE_CYCLE", "Engine simulation cycle", True, "one cycle completed")


def check_dockerfiles() -> dict[str, Any]:
    root = Path(".")
    dash = (root / "Dockerfile.dashboard").is_file()
    eng = (root / "Dockerfile.engine").is_file()
    ok = dash and eng
    return _result(
        "DOCKERFILES",
        "Northflank Dockerfiles",
        ok,
        f"dashboard={dash} engine={eng}",
        "Ensure Dockerfile.dashboard and Dockerfile.engine exist in repo root",
    )


def check_frontend_build() -> dict[str, Any]:
    ok = Path("frontend/dist/index.html").is_file()
    return _result(
        "FRONTEND_BUILD",
        "Frontend production build",
        ok,
        "frontend/dist present" if ok else "missing",
        "cd frontend && npm run build",
    )


def check_zmq_env() -> dict[str, Any]:
    host = os.getenv("ZMQ_HOST", "127.0.0.1").strip()
    cmd_port = os.getenv("ZMQ_COMMAND_PORT", "32768")
    ok = bool(host)
    return _result(
        "ZMQ_ENV",
        "ZeroMQ tunnel config",
        ok,
        f"host={host} cmd_port={cmd_port}",
        "Set ZMQ_HOST to tunnel endpoint for cloud engine → local MT5",
    )


def check_phase_schedule() -> dict[str, Any]:
    from src.engine.config import QuantAIConfig, resolve_phase

    config = QuantAIConfig.load(auto_phase=True)
    resolved = resolve_phase(auto=True)
    env_phase = os.getenv("QUANTAI_PHASE", "auto")
    mismatch = env_phase not in ("", "auto") and env_phase != resolved
    ok = not mismatch and config.current_phase == resolved
    detail = f"schedule={resolved} engine={config.current_phase} env={env_phase or 'auto'}"
    return _result(
        "PHASE_SCHEDULE",
        "Engine phase vs BST schedule",
        ok,
        detail,
        "Set QUANTAI_PHASE=auto or match current round",
    )


def check_competition_ohlcv() -> dict[str, Any]:
    from src.bridges.factory import create_live_connector

    conn = create_live_connector()
    zmq_bars = 0
    try:
        df = conn.get_ohlcv("EUR/USD", "M15", 320)
        zmq_bars = len(df) if df is not None else 0
    finally:
        conn.close()

    mt5_bars = 0
    try:
        import MetaTrader5 as mt5
        from src.integrations.mt5_session import ensure_mt5_session

        ok, _ = ensure_mt5_session(require_login=False)
        if ok:
            rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M15, 0, 320)
            if rates is None or len(rates) == 0:
                rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M15, 1, 320)
            mt5_bars = len(rates) if rates is not None else 0
    except Exception:
        mt5_bars = 0

    passed = zmq_bars >= 50 or mt5_bars >= 50
    return _result(
        "COMPETITION_OHLCV",
        "OHLCV bar depth (ZMQ or MT5 fallback)",
        passed,
        f"zmq={zmq_bars} mt5={mt5_bars} (need >=50 on at least one path)",
        "Recompile DWX EA; verify EURUSD in MarketWatch",
    )


def check_reconciliation_critical() -> dict[str, Any]:
    snapshot_path = Path("data/operator_snapshot.json")
    if not snapshot_path.exists():
        return _result(
            "RECONCILIATION",
            "Reconciliation status",
            True,
            "no operator snapshot yet",
        )
    try:
        import json

        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _result("RECONCILIATION", "Reconciliation status", True, "snapshot unreadable")

    recon = snapshot.get("reconciliation") or {}
    status = str(recon.get("status", "GREEN")).upper()
    critical = [
        i for i in recon.get("issues", [])
        if not i.get("passed", True) and i.get("severity") == "CRITICAL"
    ]
    passed = status != "RED" and len(critical) == 0
    detail = f"status={status} critical_failures={len(critical)}"
    return _result(
        "RECONCILIATION",
        "Reconciliation status",
        passed,
        detail,
        "Run scripts/repair_trade_journal.py and reconcile positions",
    )


def run_preflight(zmq_only: bool = False, with_cycle: bool = False, deep: bool = False, competition: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        check_account_profile(),
        check_config_symbols(),
        check_risk_self_test(),
        check_dashboard_auth(),
        check_tick_stream(zmq_only=zmq_only),
        check_dockerfiles(),
        check_frontend_build(),
        check_zmq_env(),
    ]
    if deep:
        from src.operator.mt5_checks import run_mt5_checks

        mt5_result = run_mt5_checks(zmq_only=zmq_only, with_cycle=False)
        checks.extend(mt5_result.get("checks", []))
    if competition:
        checks.extend([
            check_competition_ohlcv(),
            check_reconciliation_critical(),
            check_phase_schedule(),
        ])
    if with_cycle:
        checks.append(check_engine_sim_cycle())

    passed = sum(1 for c in checks if c["passed"])
    return {
        "passed": passed,
        "total": len(checks),
        "ready": passed == len(checks),
        "checks": checks,
        "deep": deep,
        "competition": competition,
    }
