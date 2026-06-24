"""Unified MT5 connectivity checks — shared by CLI, preflight, and watchdog."""

from __future__ import annotations

import json
from typing import Any

from src.operator.preflight import COMPETITION_SYMBOLS


def _mt5_symbol(symbol: str) -> str:
    return symbol.replace("/", "")


def _result(code: str, label: str, passed: bool, detail: str = "", remediation: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "passed": passed,
        "detail": detail,
        "remediation": remediation,
    }


def check_mt5_python_api() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        import MetaTrader5 as mt5
    except ImportError:
        checks.append(
            _result(
                "MT5_PACKAGE",
                "MetaTrader5 package",
                False,
                "pip install MetaTrader5 metatrader5-mcp",
                "Install MetaTrader5 Python package",
            ),
        )
        return checks

    from src.integrations.mt5_session import ensure_mt5_session, load_mt5_credentials

    creds = load_mt5_credentials()
    if not all([creds.login, creds.password, creds.server]):
        checks.append(
            _result(
                "MT5_CREDENTIALS",
                "MT5 credentials",
                False,
                "set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env",
            ),
        )
        return checks

    ok_session, detail = ensure_mt5_session(require_login=True)
    if not ok_session:
        checks.append(
            _result(
                "MT5_SESSION",
                "MT5 session",
                False,
                f"{detail}. Is MT5 running, logged in, and Algorithmic Trading enabled?",
            ),
        )
        return checks

    account = mt5.account_info()
    if account is None:
        checks.append(_result("MT5_ACCOUNT", "MT5 account info", False, "account_info() returned None"))
        return checks

    checks.append(
        _result(
            "MT5_ACCOUNT",
            "MT5 login + account",
            True,
            f"{detail}; equity={account.equity:.2f} balance={account.balance:.2f} server={account.server}",
        ),
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
    sym_detail = f"{visible}/{len(COMPETITION_SYMBOLS)} symbols visible"
    if missing:
        sym_detail += f"; missing: {', '.join(missing)}"
    checks.append(
        _result(
            "MT5_SYMBOLS",
            "Competition symbols in MarketWatch",
            symbols_ok,
            sym_detail,
            "Add missing symbols to MarketWatch in MT5",
        ),
    )

    timeframes = [
        ("M15", mt5.TIMEFRAME_M15),
        ("H1", mt5.TIMEFRAME_H1),
    ]
    for tf_name, tf_const in timeframes:
        rates = mt5.copy_rates_from_pos("EURUSD", tf_const, 0, 320)
        if rates is None or len(rates) == 0:
            rates = mt5.copy_rates_from_pos("EURUSD", tf_const, 1, 320)
        bar_count = len(rates) if rates is not None else 0
        rates_ok = bar_count >= 50
        checks.append(
            _result(
                f"MT5_BARS_{tf_name}",
                f"Historical bars (EURUSD {tf_name})",
                rates_ok,
                f"{bar_count} bars (need >=50)",
            ),
        )

    return checks


def check_zeromq_bridge() -> list[dict[str, Any]]:
    from src.bridges.factory import create_live_connector, connector_bridge_type

    checks: list[dict[str, Any]] = []
    conn = create_live_connector()
    bridge = connector_bridge_type(conn)
    try:
        account = conn.get_account_info()
        account_ok = account.get("status") != "error" and "equity" in account
        checks.append(
            _result(
                "ZMQ_ACCOUNT",
                f"Live bridge ({bridge}) ACCOUNT",
                account_ok,
                json.dumps(
                    {k: account[k] for k in ("equity", "balance", "margin", "trade_allowed") if k in account},
                ),
                "Start DWX_ZeroMQ_Server as MT5 Service",
            ),
        )

        positions = conn.get_positions()
        checks.append(
            _result(
                "ZMQ_POSITIONS",
                f"Live bridge ({bridge}) POSITIONS",
                isinstance(positions, list),
                f"{len(positions)} open positions",
            ),
        )

        df = conn.get_ohlcv("EUR/USD", "M15", 320)
        data_ok = df is not None and len(df) >= 50
        checks.append(
            _result(
                "ZMQ_DATA",
                f"Live bridge ({bridge}) DATA (EUR/USD M15)",
                data_ok,
                f"{len(df) if df is not None else 0} bars (need >=50)",
            ),
        )

        tick = None
        poll = getattr(conn, "poll_ticks", None)
        if callable(poll):
            tick = poll()
        checks.append(
            _result(
                "ZMQ_TICK",
                f"Live bridge ({bridge}) tick poll",
                tick is not None,
                "received tick" if tick else "no tick yet",
                "Verify ZMQ tick port and MarketWatch subscriptions",
            ),
        )
    finally:
        conn.close()
    return checks


def check_simulation_cycle() -> dict[str, Any]:
    import os

    from src.engine.config import QuantAIConfig
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase=os.getenv("QUANTAI_PHASE", "round1"))
    engine = TradingEngine(config=config, simulation=True)
    engine.start()
    engine.run_cycle()
    return _result("ENGINE_CYCLE", "Simulation single cycle", True, "one cycle completed")


def run_mt5_checks(zmq_only: bool = False, with_cycle: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if not zmq_only:
        checks.extend(check_mt5_python_api())
    checks.extend(check_zeromq_bridge())
    if with_cycle:
        checks.append(check_simulation_cycle())

    passed = sum(1 for c in checks if c["passed"])
    return {
        "passed": passed,
        "total": len(checks),
        "ready": passed == len(checks),
        "checks": checks,
    }
