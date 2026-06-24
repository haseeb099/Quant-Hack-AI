#!/usr/bin/env python3
"""Launch the MT5 MCP server using credentials from the project .env file."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

_RETRY_SECONDS = float(os.getenv("MT5_MCP_CONNECT_RETRY_SECONDS", "3"))
_RETRY_ATTEMPTS = int(os.getenv("MT5_MCP_CONNECT_RETRY_ATTEMPTS", "20"))


def _connect_mt5() -> tuple[bool, str]:
    from src.integrations.mt5_config import ensure_mt5_api_enabled, read_mt5_profile
    from src.integrations.mt5_session import ensure_mt5_session, load_mt5_credentials

    creds = load_mt5_credentials()
    missing = [
        name
        for name, value in {
            "MT5_LOGIN": creds.login,
            "MT5_PASSWORD": creds.password,
            "MT5_SERVER": creds.server,
        }.items()
        if not value
    ]
    if missing:
        return False, (
            "Missing MT5 credentials in .env: "
            + ", ".join(missing)
            + ". Copy .env.example and fill in your competition account details."
        )

    profile = read_mt5_profile()
    if profile.get("server") and creds.server and profile["server"] != creds.server:
        print(
            f"Note: MT5 profile server is {profile['server']} but MT5_SERVER="
            f"{creds.server}. Using both during login attempts.",
            file=sys.stderr,
        )

    if not profile.get("api_enabled"):
        _, api_detail = ensure_mt5_api_enabled()
        print(api_detail, file=sys.stderr)

    last_detail = "MT5 connection not attempted"
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        ok, detail = ensure_mt5_session(require_login=True, auto_enable_api=False)
        if ok:
            return True, detail
        last_detail = detail
        if attempt < _RETRY_ATTEMPTS:
            print(
                f"MT5 connect attempt {attempt}/{_RETRY_ATTEMPTS} failed: {detail}. "
                f"Retrying in {_RETRY_SECONDS:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(_RETRY_SECONDS)

    return False, last_detail


def main() -> int:
    ok, detail = _connect_mt5()
    if not ok:
        print(f"MT5 session failed: {detail}", file=sys.stderr)
        print(
            "MCP cannot start until MT5 is running, logged in, and API access is enabled. "
            "Checklist: 1) Open MetaTrader 5 and log into account "
            f"{os.getenv('MT5_LOGIN', '(set MT5_LOGIN)')} on server "
            f"{os.getenv('MT5_SERVER', '(set MT5_SERVER)')}  "
            "2) Click the Algo Trading button in the MT5 toolbar until it is green  "
            "3) Tools -> Options -> Expert Advisors -> Allow algorithmic trading  "
            "4) Restart MT5 if you changed those settings  "
            "5) Reload MCP in Cursor (Settings -> MCP -> metatrader5).",
            file=sys.stderr,
        )
        return 1

    print(f"MT5 session ready: {detail}", file=sys.stderr)

    log_level = os.getenv("MT5_MCP_LOG_LEVEL", "INFO")
    _run_mcp_server(log_level)
    return 0


def _run_mcp_server(log_level: str) -> None:
    """Start FastMCP without re-initializing MT5.

    metatrader5_mcp.main.main() always reloads .env and calls mt5.initialize()
    with login/password when credentials are present. That second login attempt
    breaks an already-attached session and exits with "check your credentials".
    """
    from metatrader5_mcp import (  # noqa: F401
        prompts,
        tools_connection,
        tools_market,
        tools_positions,
        tools_status,
        tools_trading,
    )
    from metatrader5_mcp.logger import configure_logging, logger
    from metatrader5_mcp.utils import mcp

    configure_logging(log_level)
    logger.info("MetaTrader 5 MCP server starting (reusing attached MT5 session)")
    mcp.run()


if __name__ == "__main__":
    raise SystemExit(main())
