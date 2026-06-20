"""WebSocket live state broadcaster."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.web.runtime_state import read_state
from src.web.state_publisher import register_state_listener

logger = logging.getLogger(__name__)

BROADCAST_INTERVAL_SEC = 5


class ConnectionManager:
    """Manages WebSocket clients and broadcasts state updates."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._task: asyncio.Task | None = None
        self._last_hash: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener_registered = False

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        self._ensure_listener()
        state = read_state()
        await websocket.send_json({"type": "state", "payload": state})

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def _on_state_change(self, state: dict[str, Any]) -> None:
        if not self._connections or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.broadcast({"type": "state", "payload": state}),
            self._loop,
        )

    def _ensure_listener(self) -> None:
        if not self._listener_registered:
            register_state_listener(self._on_state_change)
            self._listener_registered = True

    async def _poll_loop(self) -> None:
        while True:
            try:
                state = read_state()
                payload = json.dumps(state, sort_keys=True, default=str)
                if payload != self._last_hash:
                    self._last_hash = payload
                    await self.broadcast({"type": "state", "payload": state})
            except Exception:
                logger.debug("WS broadcast error", exc_info=True)
            await asyncio.sleep(BROADCAST_INTERVAL_SEC)

    def start_background(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._poll_loop())

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket) -> None:
    auth_token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if auth_token:
        header = websocket.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
        query = websocket.query_params.get("token", "")
        if token != auth_token and query != auth_token and websocket.headers.get("X-Dashboard-Token") != auth_token:
            await websocket.close(code=1008, reason="Unauthorized")
            return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong", "payload": {}})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
