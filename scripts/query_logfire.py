"""Query Logfire traces via local logfire-mcp (read token from .env)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


async def run_query(query: str, age_minutes: int = 360) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if load_dotenv:
        load_dotenv(ROOT / ".env")

    token = os.getenv("LOGFIRE_READ_TOKEN") or os.getenv("LOGFIRE_TOKEN")
    if not token:
        raise SystemExit("LOGFIRE_TOKEN not set in environment")

    env = os.environ.copy()
    env["LOGFIRE_READ_TOKEN"] = token
    env["LOGFIRE_BASE_URL"] = os.getenv("LOGFIRE_BASE_URL", "https://logfire-eu.pydantic.dev")

    params = StdioServerParameters(
        command="uvx",
        args=["logfire-mcp@latest"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "arbitrary_query",
                arguments={"query": query, "age": age_minutes},
            )
            if result.isError:
                return json.dumps({"error": result.content})
            if not result.content:
                return json.dumps({"error": "empty response", "structured": result.structuredContent})
            parts = []
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else json.dumps(result.structuredContent or {})


def main() -> None:
    age = int(sys.argv[2]) if len(sys.argv) > 2 else 360
    query = sys.argv[1] if len(sys.argv) > 1 else (
        "SELECT message, level, span_name, start_timestamp "
        "FROM records WHERE level >= 'error' "
        "ORDER BY start_timestamp DESC LIMIT 25"
    )
    print(asyncio.run(run_query(query, age)))


if __name__ == "__main__":
    main()
