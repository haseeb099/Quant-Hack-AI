#!/usr/bin/env python3
from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from src.web.app import create_app

port = 8126
app = create_app()


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="debug")


threading.Thread(target=run, daemon=True).start()
time.sleep(2)

key = "dGhlIHNhbXBsZSBub25jZQ=="
req = (
    f"GET /ws/live HTTP/1.1\r\n"
    f"Host: 127.0.0.1:{port}\r\n"
    f"Upgrade: websocket\r\n"
    f"Connection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\n"
    f"Sec-WebSocket-Version: 13\r\n"
    f"\r\n"
)
with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
    sock.sendall(req.encode())
    data = sock.recv(4096)
    print(data.decode("latin1", errors="replace"))
