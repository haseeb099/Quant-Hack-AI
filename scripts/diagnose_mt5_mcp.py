#!/usr/bin/env python3
"""Diagnose MT5 MCP prerequisites and print fix steps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _mt5_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "terminal64.exe" in result.stdout


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from src.integrations.mt5_config import read_mt5_profile
    from src.integrations.mt5_session import ensure_mt5_session, load_mt5_credentials

    print("MT5 MCP diagnostics")
    print("=" * 40)

    creds = load_mt5_credentials()
    profile = read_mt5_profile()
    running = _mt5_running()

    print(f"MT5 terminal running: {running}")
    print(f"MT5 profile login:    {profile.get('login')}")
    print(f"MT5 profile server:  {profile.get('server')}")
    print(f"Experts/Api enabled:  {profile.get('api_enabled')}")
    print(f"Algo trading enabled: {profile.get('algo_enabled')}")
    print(f".env MT5_LOGIN:       {creds.login}")
    print(f".env MT5_SERVER:      {creds.server}")

    if not profile.get("api_enabled"):
        print("\nFIX: Close MT5, run `python scripts/enable_mt5_api.py`, restart MT5.")

    if profile.get("server") and creds.server and profile["server"] != creds.server:
        print(
            f"\nWARN: .env MT5_SERVER ({creds.server}) differs from MT5 profile "
            f"({profile['server']}). Update .env to the profile server name."
        )

    ok, detail = ensure_mt5_session(require_login=True, auto_enable_api=False)
    print(f"\nPython API session: {'OK' if ok else 'FAIL'}")
    print(detail)

    if not ok:
        if not running:
            print("\nFIX: Start MetaTrader 5 and log into your competition account.")
        elif "Authorization failed" in detail:
            print(
                "\nFIX: In the MT5 window, log in manually (File -> Login to Trade Account), "
                "click the green 'Algo Trading' toolbar button, then reload MCP in Cursor."
            )
        return 1

    print("\nMCP launcher should work. Reload metatrader5 in Cursor Settings -> MCP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
