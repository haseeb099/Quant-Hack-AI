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
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

DEFAULT_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
COMPETITION_SYMBOLS = [
    "AUD/USD",
    "EUR/CHF",
    "EUR/GBP",
    "EUR/USD",
    "GBP/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
    "XAG/USD",
    "XAU/USD",
    "BAR/USD",
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
]


def _mt5_symbol(symbol: str) -> str:
    return symbol.replace("/", "")


def _print_result(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def test_mt5_python_api() -> bool:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return _print_result(
            "MetaTrader5 package",
            False,
            "run: pip install MetaTrader5 metatrader5-mcp",
        )

    path = os.getenv("MT5_PATH", DEFAULT_MT5_PATH)
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not all([login, password, server]):
        return _print_result(
            "MT5 credentials",
            False,
            "set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env",
        )

    if not mt5.initialize(path=path):
        err = mt5.last_error()
        return _print_result(
            "MT5 initialize",
            False,
            f"{err}. Is the MT5 terminal running with Algorithmic Trading enabled?",
        )

    try:
        if not mt5.login(int(login), password=password, server=server):
            err = mt5.last_error()
            return _print_result("MT5 login", False, str(err))

        account = mt5.account_info()
        if account is None:
            return _print_result("MT5 account info", False, "account_info() returned None")

        ok = _print_result(
            "MT5 login + account",
            True,
            f"equity={account.equity:.2f} balance={account.balance:.2f} server={account.server}",
        )

        visible = 0
        missing: list[str] = []
        for symbol in COMPETITION_SYMBOLS:
            mt5_symbol = _mt5_symbol(symbol)
            mt5.symbol_select(mt5_symbol, True)
            info = mt5.symbol_info(mt5_symbol)
            if info is None or not info.visible:
                missing.append(symbol)
            else:
                visible += 1

        symbols_ok = len(missing) == 0
        detail = f"{visible}/{len(COMPETITION_SYMBOLS)} symbols visible"
        if missing:
            detail += f"; missing: {', '.join(missing)}"
        ok = _print_result("Competition symbols in MarketWatch", symbols_ok, detail) and ok

        rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M15, 0, 10)
        rates_ok = rates is not None and len(rates) > 0
        ok = _print_result(
            "Historical bars (EURUSD M15)",
            rates_ok,
            f"{len(rates) if rates is not None else 0} bars",
        ) and ok
        return ok
    finally:
        mt5.shutdown()


def test_zeromq_bridge() -> bool:
    from src.bridges.zeromq_connector import ZeroMQConnector

    conn = ZeroMQConnector()
    if not conn.connect():
        return _print_result(
            "ZeroMQ bridge",
            False,
            "could not connect on ports 32768-32770. Start mql5/DWX_ZeroMQ_Server.mq5 as a Service.",
        )

    try:
        ok = True
        account = conn.get_account_info()
        account_ok = account.get("status") != "error" and "equity" in account
        ok = _print_result(
            "ZeroMQ ACCOUNT",
            account_ok,
            json.dumps({k: account[k] for k in ("equity", "balance", "margin") if k in account}),
        ) and ok

        positions = conn.get_positions()
        ok = _print_result(
            "ZeroMQ POSITIONS",
            isinstance(positions, list),
            f"{len(positions)} open positions",
        ) and ok

        df = conn.get_ohlcv("EUR/USD", "M15", 20)
        data_ok = df is not None and len(df) > 0
        ok = _print_result(
            "ZeroMQ DATA (EUR/USD M15)",
            data_ok,
            f"{len(df) if df is not None else 0} bars",
        ) and ok
        return ok
    finally:
        conn.close()


def test_simulation_cycle() -> bool:
    from src.engine.config import QuantAIConfig
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase=os.getenv("QUANTAI_PHASE", "round1"))
    engine = TradingEngine(config=config, simulation=True)
    engine.start()
    engine.run_cycle()
    return _print_result("Simulation single cycle", True, "completed without exception")


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantAI MT5 pre-competition checklist")
    parser.add_argument("--zmq-only", action="store_true", help="Skip MetaTrader5 Python API tests")
    parser.add_argument("--with-cycle", action="store_true", help="Run one simulation cycle")
    args = parser.parse_args()

    print("QuantAI MT5 pre-competition checklist")
    print("=" * 40)

    results: list[bool] = []
    if not args.zmq_only:
        results.append(test_mt5_python_api())
    results.append(test_zeromq_bridge())
    if args.with_cycle:
        results.append(test_simulation_cycle())

    print("=" * 40)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"All checks passed ({passed}/{total}). Ready for live dry-run.")
        return 0

    print(f"{passed}/{total} checks passed. Fix failures before competition launch.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
