#!/usr/bin/env python3
"""Pre-competition readiness checks for QuantAI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.operator.preflight import run_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI pre-competition preflight")
    parser.add_argument("--zmq-only", action="store_true", help="Skip LiveFeed, test ZMQ poll only")
    parser.add_argument("--with-cycle", action="store_true", help="Run one simulation cycle")
    args = parser.parse_args()

    result = run_preflight(zmq_only=args.zmq_only, with_cycle=args.with_cycle)
    for check in result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        detail = check.get("detail", "")
        suffix = f" — {detail}" if detail else ""
        print(f"[{status}] {check['label']}{suffix}")

    passed = result["passed"]
    total = result["total"]
    print(f"\nPreflight: {passed}/{total} checks passed")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
