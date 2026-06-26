#!/usr/bin/env python3
"""QuantAI — Regime-aware multi-agent trading system.

Usage:
    python main.py --mode live --phase round1
    python main.py --mode simulate --phase round1
    python main.py --mode single-cycle --phase round1
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from src.engine.config import QuantAIConfig
from src.engine.engine_lock import acquire_live_engine_lock
from src.engine.trading_engine import TradingEngine
from src.utils.logger import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantAI Trading System")
    parser.add_argument(
        "--mode",
        choices=["live", "simulate", "single-cycle"],
        default="simulate",
        help="Execution mode (default: simulate)",
    )
    parser.add_argument(
        "--phase",
        choices=["auto", "round1", "round2", "round3", "finals"],
        default=os.getenv("QUANTAI_PHASE", "auto"),
        help="Competition phase — 'auto' follows BST schedule (default: auto)",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--no-logfire", action="store_true", help="Disable Logfire")
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Start FastAPI dashboard in a background thread on port 8080",
    )
    parser.add_argument("--dashboard-port", type=int, default=8080, help="Dashboard port")
    parser.add_argument(
        "--with-watchdog",
        action="store_true",
        help="Start operator watchdog in background (default for live + dashboard)",
    )
    parser.add_argument(
        "--no-watchdog",
        action="store_true",
        help="Disable operator watchdog even in live mode",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    setup_logging(level=args.log_level, enable_logfire=not args.no_logfire)

    acquire_live_engine_lock(args.mode)

    if args.with_dashboard:
        import threading

        from src.web.dashboard import run_dashboard

        dashboard_thread = threading.Thread(
            target=run_dashboard,
            kwargs={"host": "0.0.0.0", "port": args.dashboard_port},
            daemon=True,
            name="quantai-dashboard",
        )
        dashboard_thread.start()
        import time
        time.sleep(1.5)  # let dashboard bind before engine publishes state

    from src.operator.watchdog_daemon import (
        start_watchdog_thread,
        watchdog_dashboard_url,
        watchdog_enabled_for_mode,
        watchdog_interval_sec,
    )

    use_watchdog = args.with_watchdog or (
        not args.no_watchdog and watchdog_enabled_for_mode(args.mode, args.with_dashboard)
    )
    if use_watchdog:
        start_watchdog_thread(
            interval_sec=watchdog_interval_sec(),
            dashboard_url=watchdog_dashboard_url(args.dashboard_port),
        )

    config = QuantAIConfig.load(
        phase=args.phase if args.phase != "auto" else "auto",
        auto_phase=args.phase == "auto",
    )
    simulation = args.mode in ("simulate", "single-cycle")

    engine = TradingEngine(
        config=config,
        simulation=simulation,
        cycle_minutes=config.cycle_minutes(),
        auto_phase=args.phase == "auto",
    )

    if args.with_dashboard:
        from src.web.engine_registry import register_engine

        register_engine(engine)

    if args.mode == "single-cycle":
        engine.start()
        engine.run_cycle()
    else:
        engine.run()


if __name__ == "__main__":
    main()
