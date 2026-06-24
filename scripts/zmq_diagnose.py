#!/usr/bin/env python3
"""Diagnose MT5 ZeroMQ bridge — ports, EA response, and fix steps."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

PORTS = (32768, 32769, 32770)


def port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def find_port_pid(port: int) -> str | None:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            errors="replace",
        )
    except Exception:
        return None
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    return None


def main() -> int:
    print("QuantAI ZeroMQ bridge diagnostic")
    print("=" * 40)

    all_ports = True
    for port in PORTS:
        listening = port_listening(port)
        pid = find_port_pid(port) if listening else None
        status = "LISTENING" if listening else "CLOSED"
        print(f"Port {port}: {status}" + (f" (PID {pid})" if pid else ""))
        all_ports = all_ports and listening

    if not all_ports:
        print("\nFix: Start DWX_ZeroMQ_Server in MT5 (Navigator -> Services -> Start)")
        print("     Compile mql5/DWX_ZeroMQ_Server.mq5 first if not installed.")
        return 1

    from src.bridges.zeromq_connector import ZeroMQConnector

    conn = ZeroMQConnector()
    print("\nConnecting and verifying ACCOUNT ping...")
    if conn.connect():
        account = conn.get_account_info()
        print("[PASS] EA responded:", json.dumps(account, default=str)[:200])
        ticks = conn.poll_ticks()
        if ticks:
            print("[PASS] Tick stream:", json.dumps(ticks, default=str)[:120])
        else:
            print("[WARN] No tick yet (may arrive within 1-2s after connect)")

        df = conn.get_ohlcv("EUR/USD", "M15", 320)
        bar_count = len(df) if df is not None else 0
        if bar_count >= 50:
            print(f"[PASS] DATA EUR/USD M15: {bar_count} bars")
        else:
            print(f"[FAIL] DATA EUR/USD M15: {bar_count} bars (need >=50)")
            conn.close()
            return 1

        conn.close()
        return 0

    print("[FAIL]", conn.last_error or "EA not responding")
    print("\nPorts are open but the EA is not answering. Try in order:")
    print("  1. MT5 -> Tools -> Options -> Expert Advisors -> enable Algorithmic Trading")
    print("  2. Navigator -> Services -> stop DWX_ZeroMQ_Server, then Start again")
    print("  3. Check Experts/Journal tab for 'QuantAI ZeroMQ Server started'")
    print("  4. Close other Python scripts using ports 32768-32770, then re-run this script")
    print("  5. Recompile mql5/DWX_ZeroMQ_Server.mq5 after mql-zmq library install")
    conn.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
