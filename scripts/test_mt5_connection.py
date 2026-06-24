#!/usr/bin/env python3
"""Pre-competition MT5 connectivity checklist.

Tests:
  1. MetaTrader5 Python API (used by the MCP server)
  2. ZeroMQ bridge (used by live trading)
  3. All 15 competition symbols
  4. Optional single simulation cycle

Usage:
  python scripts/test_mt5_connection.py
  python scripts/test_mt5_connection.py --zmq-only
  python scripts/test_mt5_connection.py --with-cycle
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.operator.mt5_checks import run_mt5_checks


def _print_result(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI MT5 pre-competition checklist")
    parser.add_argument("--zmq-only", action="store_true", help="Skip MetaTrader5 Python API tests")
    parser.add_argument("--with-cycle", action="store_true", help="Run one simulation cycle")
    args = parser.parse_args()

    print("QuantAI MT5 pre-competition checklist")
    print("=" * 40)

    result = run_mt5_checks(zmq_only=args.zmq_only, with_cycle=args.with_cycle)
    outcomes: list[bool] = []
    for check in result["checks"]:
        outcomes.append(
            _print_result(check["label"], check["passed"], check.get("detail", "")),
        )

    try:
        import MetaTrader5 as mt5

        mt5.shutdown()
    except Exception:
        pass

    print("=" * 40)
    passed = sum(outcomes)
    total = len(outcomes)
    if all(outcomes):
        print(f"All checks passed ({passed}/{total}). Ready for live dry-run.")
        return 0

    print(f"{passed}/{total} checks passed. Fix failures before competition launch.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
