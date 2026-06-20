#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from src.web.ws import manager, websocket_endpoint
from src.web.routes import agents, instruments, positions, risk, status, trades

FRONTEND_DIST = Path("frontend/dist")


def build_manual() -> FastAPI:
    app = FastAPI(title="QuantAI Dashboard", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(status.router)
    app.include_router(trades.router)
    app.include_router(positions.router)
    app.include_router(agents.router)
    app.include_router(risk.router)
    app.include_router(instruments.router)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await manager.connect(websocket)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup():
        import asyncio as aio
        manager.start_background(aio.get_running_loop())

    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        @app.get("/")
        async def serve_index():
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


def raw_probe(port: int) -> str:
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    req = (
        f"GET /ws/live HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(req.encode())
        return sock.recv(4096).decode("latin1", errors="replace").split("\r\n\r\n", 1)[0]


def run_case(name: str, app: FastAPI, port: int) -> None:
    def run() -> None:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    threading.Thread(target=run, daemon=True).start()
    time.sleep(2)
    print(f"=== {name} ===")
    print(raw_probe(port).split("\r\n")[0])

    async def ws_test() -> None:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/live") as ws:
            print("ws recv", (await ws.recv())[:60])

    try:
        asyncio.run(ws_test())
    except Exception as exc:
        print("ws fail", exc)


if __name__ == "__main__":
    from src.web.app import create_app

    run_case("create_app", create_app(), 8128)
    time.sleep(1)
    run_case("manual", build_manual(), 8127)
