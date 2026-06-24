"""Launch Logfire MCP for Cursor (loads LOGFIRE_TOKEN from project .env)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    _load_env()
    token = os.getenv("LOGFIRE_READ_TOKEN") or os.getenv("LOGFIRE_TOKEN")
    if not token:
        print("LOGFIRE_TOKEN not set — add it to .env", file=sys.stderr)
        raise SystemExit(1)

    os.environ["LOGFIRE_READ_TOKEN"] = token
    os.environ.setdefault("LOGFIRE_BASE_URL", "https://logfire-eu.pydantic.dev")

    cmd = [
        "uvx",
        "logfire-mcp@latest",
        f"--read-token={token}",
        f"--base-url={os.environ['LOGFIRE_BASE_URL']}",
    ]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
