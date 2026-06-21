#!/usr/bin/env python3
"""Competition-day automated verification — CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.operator.verification import get_verification_status, run_verification


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI competition-day verification")
    parser.add_argument("--full", action="store_true", help="Run full pytest suite (slow)")
    parser.add_argument("--status", action="store_true", help="Show last verification only")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(get_verification_status(), indent=2))
        return 0

    result = run_verification(quick=not args.full, persist=True)
    for check in result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        detail = check.get("detail", "")
        suffix = f" — {detail}" if detail else ""
        print(f"[{status}] {check['label']}{suffix}")

    session = result.get("session", {})
    print(f"\nSession: {session.get('label', 'unknown')}")
    print(f"Verification: {result['passed']}/{result['total']} checks passed")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
