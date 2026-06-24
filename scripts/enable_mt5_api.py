#!/usr/bin/env python3
"""Enable MT5 Python API access and print the saved broker server name."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.integrations.mt5_config import ensure_mt5_api_enabled, read_mt5_profile

    profile = read_mt5_profile()
    print("MT5 profile:")
    print(f"  login:  {profile.get('login')}")
    print(f"  server: {profile.get('server')}")
    print(f"  api_enabled: {profile.get('api_enabled')}")
    print(f"  algo_enabled: {profile.get('algo_enabled')}")
    print(f"  dll_import_enabled: {profile.get('dll_import_enabled')}")
    if profile.get("path"):
        print(f"  config: {profile['path']}")

    ok, detail = ensure_mt5_api_enabled()
    print(detail)
    if not ok:
        return 1

    if profile.get("server"):
        print(
            f"\nSet MT5_SERVER={profile['server']} in .env "
            "(must match the server name shown in MT5)."
        )
    print("\nRestart MetaTrader 5, log in, then reload the MCP server in Cursor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
