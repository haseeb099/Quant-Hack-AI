#!/usr/bin/env python3
"""Full-stack live trade — minimal startup to avoid ZMQ thread contention."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ.setdefault("QUANTAI_MIN_CONFIDENCE", "0.55")

from src.engine.config import QuantAIConfig
from src.engine.trading_engine import TradingEngine
from src.utils.logger import setup_logging


def main() -> int:
    setup_logging(level="INFO")
    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=False)

    if not engine.connector.connect():
        print("FAIL: ZeroMQ not connected")
        return 1
    time.sleep(1.5)
    engine._init_mt5_session()

    account = engine.connector.get_account_info()
    equity = account.get("equity", 1.0)
    engine.drawdown_guard.reset(equity)
    engine._peak_equity = equity
    engine._initial_equity = equity

    dd = engine.drawdown_guard.update(equity)
    ms = engine.margin_monitor.check(
        equity=equity, used_margin=0, gross_exposure=0, largest_position_pct=0,
    )
    peer = engine.peer_monitor.update({
        "peer_count": 100,
        "avg_return": 0.02,
        "avg_drawdown": 0.04,
        "top_performer_return": 0.06,
        "our_return": 0,
        "our_rank": 55,
    })

    candidates = ["SOL/USD", "ETH/USD", "BTC/USD", "EUR/CHF"]
    for symbol in candidates:
        m15 = engine._get_ohlcv(symbol, "M15")
        if m15 is None or len(m15) < 50:
            print(f"Skip {symbol}: insufficient data")
            continue
        print(f"\n=== FULL STACK: {symbol} ===")
        engine._process_symbol(
            symbol, equity, dd, ms, "ny", 0.0,
            peer_adj=engine.peer_monitor.sizing_adjustment(),
            peer_sentiment=peer.crowd_bias,
        )
        positions = engine.connector.get_positions()
        if positions:
            print("\n=== LIVE POSITION (SL/TP on MT5) ===")
            print(json.dumps(positions, indent=2))
            engine._publish_state()
            engine.connector.close()
            return 0

    print("\nNo trade opened — agents below confidence or market closed.")
    engine._publish_state()
    engine.connector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
