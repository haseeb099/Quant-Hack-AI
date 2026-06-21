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
        feed = LiveFeed(conn)
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


def run_preflight(zmq_only: bool = False, with_cycle: bool = False) -> dict[str, Any]:
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
    if with_cycle:
        checks.append(check_engine_sim_cycle())

    passed = sum(1 for c in checks if c["passed"])
    return {
        "passed": passed,
        "total": len(checks),
        "ready": passed == len(checks),
        "checks": checks,
    }
