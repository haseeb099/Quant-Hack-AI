#!/usr/bin/env python3
"""Launch the MT5 MCP server using credentials from the project .env file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


def _build_cli_args() -> list[str]:
    args: list[str] = []

    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    path = os.getenv("MT5_PATH", DEFAULT_MT5_PATH)

    if login:
        args.extend(["--login", login])
    if password:
        args.extend(["--password", password])
    if server:
        args.extend(["--server", server])
    if path:
        args.extend(["--path", path])

    log_level = os.getenv("MT5_MCP_LOG_LEVEL", "INFO")
    args.extend(["--log-level", log_level])
    return args


def main() -> int:
    missing = [
        name
        for name, value in {
            "MT5_LOGIN": os.getenv("MT5_LOGIN"),
            "MT5_PASSWORD": os.getenv("MT5_PASSWORD"),
            "MT5_SERVER": os.getenv("MT5_SERVER"),
        }.items()
        if not value
    ]
    if missing:
        print(
            "Missing MT5 credentials in .env: "
            + ", ".join(missing)
            + ". Copy .env.example and fill in your competition account details.",
            file=sys.stderr,
        )
        return 1

    from metatrader5_mcp.main import main as mcp_main

    mcp_main(_build_cli_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
