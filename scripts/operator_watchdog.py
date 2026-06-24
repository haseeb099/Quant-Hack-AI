#!/usr/bin/env python3
"""Continuous operator watchdog — MT5 vs engine reconciliation and risk compliance.

Usage:
  python scripts/operator_watchdog.py
  python scripts/operator_watchdog.py --interval 120 --dashboard-url http://127.0.0.1:8080
  python scripts/operator_watchdog.py --once
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.operator.watchdog import run_operator_watchdog_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI operator watchdog")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("OPERATOR_WATCHDOG_INTERVAL_SEC", "120")),
        help="Seconds between cycles (default: OPERATOR_WATCHDOG_INTERVAL_SEC or 120)",
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.getenv("OPERATOR_DASHBOARD_URL", "http://127.0.0.1:8080"),
        help="Dashboard base URL",
    )
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--zmq-only", action="store_true", help="Skip MetaTrader5 Python API checks")
    parser.add_argument(
        "--no-notion",
        action="store_true",
        help="Disable Notion alerts even when OPERATOR_ALERT_NOTION=true",
    )
    args = parser.parse_args()

    alert_notion = None if not args.no_notion else False

    def run_cycle() -> dict:
        snapshot = run_operator_watchdog_cycle(
            dashboard_url=args.dashboard_url,
            zmq_only=args.zmq_only or None,
            alert_notion=alert_notion,
            persist=True,
        )
        status = snapshot.get("status", "UNKNOWN")
        summary = snapshot.get("summary", {})
        print(
            f"[{status}] mt5={summary.get('mt5_position_count')} "
            f"engine={summary.get('engine_position_count')} "
            f"orphans={summary.get('orphan_trades')}",
        )
        return snapshot

    if args.once:
        run_cycle()
        return 0

    print(f"Operator watchdog started — interval={args.interval}s url={args.dashboard_url}")
    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            print("Stopped.")
            return 0
        except Exception as exc:
            print(f"Watchdog cycle failed: {exc}")
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
