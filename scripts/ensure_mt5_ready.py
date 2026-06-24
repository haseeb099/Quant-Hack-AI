#!/usr/bin/env python3
"""Prepare MT5 for live trading — API flags, bridge deploy hint, connectivity check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    from src.integrations.mt5_config import ensure_mt5_api_enabled, read_mt5_profile
    from src.integrations.mt5_session import ensure_mt5_session, load_mt5_credentials

    print("QuantAI MT5 live readiness")
    print("=" * 40)

    creds = load_mt5_credentials()
    profile = read_mt5_profile()
    print(f"Env login:     {creds.login} @ {creds.server}")
    print(f"Saved login:   {profile.get('login')} @ {profile.get('server')}")
    print(f"Python API:    {'on' if profile.get('api_enabled') else 'OFF'}")
    print(f"Algo trading:  {'on' if profile.get('algo_enabled') else 'OFF'}")
    print(f"DLL imports:   {'on' if profile.get('dll_import_enabled') else 'OFF'}")

    ok, detail = ensure_mt5_api_enabled()
    print(f"\nConfig: {detail}")
    if not ok:
        return 1

    ok, detail = ensure_mt5_session(require_login=True)
    print(f"\nMT5 session: {'PASS' if ok else 'FAIL'} — {detail}")
    if not ok:
        print("\nManual fix:")
        print("  1. Open MetaTrader 5 and log in as account", creds.login)
        print("  2. Server must be FTWorldwide-MainTrade (not the IP address)")
        print("  3. If login fails, update MT5_PASSWORD in .env (no quotes around password)")
        print("  4. Click Algo Trading ON in the MT5 toolbar")
        print("  5. Navigator -> Services -> Start DWX_ZeroMQ_Server")
        return 1

    deploy = ROOT / "scripts" / "deploy_mt5_bridge.ps1"
    if deploy.is_file():
        print("\nDeploying updated ZeroMQ EA...")
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(deploy)],
            check=False,
        )

    from src.bridges.factory import create_live_connector, connector_bridge_type

    try:
        conn = create_live_connector()
        bridge = connector_bridge_type(conn)
        acc = conn.get_account_info()
        conn.close()
        print(f"\nLive bridge: PASS ({bridge})")
        print(f"  equity={acc.get('equity')} trade_allowed={acc.get('trade_allowed')}")
        print("\nReady for: python main.py --mode live --phase round1 --with-dashboard")
        return 0
    except Exception as exc:
        print(f"\nLive bridge: FAIL — {exc}")
        print("Restart DWX_ZeroMQ_Server in MT5 (Navigator -> Services), then re-run this script.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
