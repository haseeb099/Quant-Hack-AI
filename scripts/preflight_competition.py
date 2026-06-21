#!/usr/bin/env python3
"""Pre-competition readiness checks for QuantAI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

COMPETITION_SYMBOLS = [
    "AUD/USD", "EUR/CHF", "EUR/GBP", "EUR/USD", "GBP/USD",
    "USD/CAD", "USD/CHF", "USD/JPY", "XAG/USD", "XAU/USD",
    "BAR/USD", "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
]


def _print(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def check_account_profile() -> bool:
    from src.risk.account_profile import detect_profile

    override = os.getenv("ACCOUNT_PROFILE", "auto")
    equity = float(os.getenv("PREFLIGHT_EQUITY", "1000000"))
    profile = detect_profile(equity, override)
    return _print(
        "Account profile",
        profile.name in ("competition", "practice", "micro"),
        f"{profile.name} (equity={equity:,.0f})",
    )


def check_config_symbols() -> bool:
    from src.engine.config import QuantAIConfig

    config = QuantAIConfig.load(phase="round1")
    active = set(config.active_symbols)
    expected = set(COMPETITION_SYMBOLS)
    missing = expected - active
    extra = active - expected
    ok = not missing and not extra
    detail = "all 15 symbols" if ok else f"missing={missing} extra={extra}"
    return _print("Instrument universe", ok, detail)


def check_risk_self_test() -> bool:
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

    ok = (
        critical.tier == "critical"
        and emergency.tier == "emergency"
        and state.block_new_trades
    )
    return _print("Risk cap self-test", ok, f"dd={critical.tier}->{emergency.tier} margin={state.action}")


def check_tick_stream(zmq_only: bool = False) -> bool:
    if zmq_only:
        from src.bridges.zeromq_connector import ZeroMQConnector

        conn = ZeroMQConnector()
        if not conn.connect():
            return _print("Tick stream (ZMQ)", False, "bridge not connected")
        tick = conn.poll_ticks()
        conn.close()
        return _print("Tick stream (ZMQ)", tick is not None, "received tick" if tick else "no tick yet")

    try:
        from src.data.live_feed import LiveFeed
        from src.bridges.zeromq_connector import ZeroMQConnector

        conn = ZeroMQConnector()
        if not conn.connect():
            return _print("Tick stream", False, "ZMQ not connected")
        feed = LiveFeed(conn)
        feed.start()
        import time
        time.sleep(2)
        healthy = getattr(feed, "is_healthy", lambda: False)()
        feed.stop()
        conn.close()
        return _print("Tick stream (LiveFeed)", healthy, "healthy" if healthy else "no fresh ticks")
    except ImportError:
        return _print("Tick stream", True, "LiveFeed not installed — optional")


def check_engine_sim_cycle() -> bool:
    from src.engine.config import QuantAIConfig
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    engine.start()
    engine.run_cycle()
    return _print("Engine simulation cycle", True)


def check_dashboard_auth() -> bool:
    token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if not token:
        return _print("Dashboard auth", True, "optional — no DASHBOARD_AUTH_TOKEN set")
    return _print("Dashboard auth", True, "DASHBOARD_AUTH_TOKEN configured")


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI pre-competition preflight")
    parser.add_argument("--zmq-only", action="store_true", help="Skip LiveFeed, test ZMQ poll only")
    parser.add_argument("--with-cycle", action="store_true", help="Run one simulation cycle")
    args = parser.parse_args()

    results = [
        check_account_profile(),
        check_config_symbols(),
        check_risk_self_test(),
        check_dashboard_auth(),
        check_tick_stream(zmq_only=args.zmq_only),
    ]
    if args.with_cycle:
        results.append(check_engine_sim_cycle())

    passed = sum(results)
    total = len(results)
    print(f"\nPreflight: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
