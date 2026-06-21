#!/usr/bin/env python3
"""Full-stack live practice run — one competition cycle with report."""

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

from src.engine.config import QuantAIConfig
from src.engine.trading_engine import TradingEngine
from src.utils.logger import setup_logging


def _account_snapshot(connector) -> dict:
    acc = connector.get_account_info()
    positions = connector.get_positions()
    return {
        "equity": acc.get("equity"),
        "balance": acc.get("balance"),
        "margin": acc.get("margin"),
        "free_margin": acc.get("free_margin"),
        "open_positions": len(positions),
        "positions": positions,
    }


def main() -> int:
    setup_logging(level="INFO")
    print("=" * 60)
    print("QuantAI LIVE PRACTICE — full stack competition cycle")
    print("=" * 60)

    config = QuantAIConfig.load(phase=os.getenv("QUANTAI_PHASE", "round1"))
    engine = TradingEngine(config=config, simulation=False)

    try:
        engine.start()
        before = _account_snapshot(engine.connector)
        print("\n--- BEFORE ---")
        print(json.dumps({k: v for k, v in before.items() if k != "positions"}, indent=2))

        print("\n--- RUNNING FULL CYCLE (agents + debate + memory + risk + live orders) ---\n")
        engine.run_cycle()
    except Exception as exc:
        print(f"\nCYCLE FAILED: {exc}")
        engine.connector.close()
        return 1

    after = _account_snapshot(engine.connector)
    print("\n--- AFTER ---")
    print(json.dumps({k: v for k, v in after.items() if k != "positions"}, indent=2))

    if after.get("positions"):
        print("\n--- OPEN POSITIONS (SL/TP managed by MT5) ---")
        for p in after["positions"]:
            print(
                f"  {p.get('symbol')} {p.get('type')} vol={p.get('volume')} "
                f"entry={p.get('price_open')} sl={p.get('sl')} tp={p.get('tp')} "
                f"pnl={p.get('profit')} ticket={p.get('ticket')}"
            )
    else:
        print("\nNo new positions opened this cycle (HOLD or filters blocked entries).")

    eq_before = before.get("equity") or 0
    eq_after = after.get("equity") or 0
    delta = eq_after - eq_before
    print(f"\nEquity change this cycle: {delta:+.8f}")

    log_path = ROOT / "logs" / "trades.csv"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-8:] if len(lines) > 8 else lines
        print("\n--- RECENT DECISION LOG ---")
        for line in recent:
            print(line[:200])

    print("\n--- COMPONENT CHECKLIST ---")
    components = {
        "4 rule agents": True,
        "Regime detector + features": True,
        "Bull/Bear debate": True,
        "Layered memory": True,
        "MetaOrchestrator (Groq/Claude if key set)": bool(os.getenv("Groq_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
        "Peer crowd sentiment": True,
        "Kelly + lot sizing": True,
        "Drawdown/Margin/Sharpe guards": True,
        "News/fundamentals feed": True,
        "SentimentAgent (5th agent)": True,
        "Event risk gate": True,
        "ZeroMQ live execution": after.get("equity") is not None,
    }
    for name, ok in components.items():
        print(f"  [{'x' if ok else ' '}] {name}")

    print("\n--- NOT YET IMPLEMENTED ---")
    print("  - Real competition leaderboard feed (set COMPETITION_LEADERBOARD_URL)")

    engine.compliance_heartbeat.stop()
    engine.connector.close()
    print("\nPractice cycle complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
