#!/usr/bin/env python3
"""Quick WebSocket smoke test for dashboard."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
import websockets

from src.web.app import create_app


def main() -> int:
    app = create_app()
    port = 8125

    def run() -> None:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(2)

    async def test() -> None:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/live") as ws:
            msg = await ws.recv()
            print("OK", msg[:120])

    asyncio.run(test())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
