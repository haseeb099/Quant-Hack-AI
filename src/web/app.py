"""FastAPI application factory for QuantAI dashboard."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.web.routes import agents, competition, control, copilot, instruments, integrations, market, memory, positions, risk, status, trades
from src.web.ws import manager, websocket_endpoint

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path("frontend/dist")


def create_app() -> FastAPI | None:
    """Create FastAPI dashboard app with REST, WebSocket, and static SPA."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        logger.warning("FastAPI not installed — dashboard unavailable")
        return None

    app = FastAPI(title="QuantAI Dashboard", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    auth_token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if auth_token:
        from starlette.middleware.base import BaseHTTPMiddleware

        class DashboardAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                path = request.url.path
                if path.startswith("/api"):
                    header = request.headers.get("Authorization", "")
                    query = request.query_params.get("token", "")
                    token = header.removeprefix("Bearer ").strip() if header else query
                    if token != auth_token and request.headers.get("X-Dashboard-Token") != auth_token:
                        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
                return await call_next(request)

        app.add_middleware(DashboardAuthMiddleware)

    app.include_router(status.router)
    app.include_router(control.router)
    app.include_router(competition.router)
    app.include_router(integrations.router)
    app.include_router(trades.router)
    app.include_router(positions.router)
    app.include_router(agents.router)
    app.include_router(risk.router)
    app.include_router(copilot.router)
    app.include_router(memory.router)
    app.include_router(instruments.router)
    app.include_router(market.router)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup() -> None:
        import asyncio

        manager.start_background(asyncio.get_running_loop())
        logger.info("Dashboard WebSocket broadcaster started on /ws/live")

    if FRONTEND_DIST.exists() and os.getenv("DASHBOARD_SERVE_SPA", "true").lower() == "true":
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/")
        async def serve_index():
            index = FRONTEND_DIST / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse(status_code=404, content={"detail": "Frontend not built"})

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve built static files and SPA fallback for client-side routes."""
            if full_path.startswith("api") or full_path.startswith("ws"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            candidate = FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            index = FRONTEND_DIST / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse(status_code=404, content={"detail": "Frontend not built"})

    return app


def run_dashboard(host: str = "0.0.0.0", port: int = 8080) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    app = create_app()
    if app is None:
        logger.error("Cannot start dashboard — install fastapi and uvicorn")
        return
    import uvicorn

    uvicorn.run(app, host=host, port=port)
