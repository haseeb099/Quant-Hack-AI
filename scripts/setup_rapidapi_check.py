#!/usr/bin/env python3
"""Validate RapidAPI intelligence configuration for competition live mode."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.intelligence.rapidapi_client import (
    fetch_company_cash_flow,
    fetch_forex_factory_calendar_window,
    fetch_yahoo_news,
    rapidapi_key,
)


def _status(ok: bool, label: str, detail: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} — {detail}")


def main() -> int:
    key = rapidapi_key()
    if not key:
        print("[FAIL] RAPIDAPI_KEY not set")
        return 1

    print(f"RapidAPI key configured ({key[:4]}…{key[-4:]})")
    failures = 0

    headlines = fetch_yahoo_news(snippet_count=5)
    _status(bool(headlines), "Yahoo Finance news", f"{len(headlines)} headlines")
    failures += 0 if headlines else 1

    events = fetch_forex_factory_calendar_window(days_ahead=0)
    _status(bool(events), "Forex Factory calendar", f"{len(events)} events today")
    failures += 0 if events else 1

    cash_flow = fetch_company_cash_flow()
    rows = (cash_flow or {}).get("cash_flow") or []
    _status(bool(rows), "Real-Time Finance cash flow", f"{len(rows)} periods for {(cash_flow or {}).get('symbol', 'n/a')}")
    failures += 0 if rows else 1

    news_source = os.getenv("NEWS_API_SOURCE", "")
    calendar_source = os.getenv("CALENDAR_SOURCE", "")
    print(f"\nConfigured sources: NEWS_API_SOURCE={news_source or 'auto'}, CALENDAR_SOURCE={calendar_source or 'auto'}")
    print(f"RAPIDAPI_FINANCE_ENABLED={os.getenv('RAPIDAPI_FINANCE_ENABLED', 'true')}")

    if failures:
        print(f"\nRapidAPI check: {3 - failures}/3 endpoints OK")
        return 1
    print("\nRapidAPI check: all endpoints OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
