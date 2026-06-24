"""FastAPI application factory for QuantAI dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.web.auth import dashboard_auth_token, is_dashboard_authorized
from src.web.routes import adaptation, agents, competition, control, copilot, demo, instruments, integrations, intelligence, market, memory, notion, operator, positions, risk, status, trades
from src.web.ws import manager, websocket_endpoint

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path("frontend/dist")


def _cors_origins() -> list[str]:
    raw = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    env = os.getenv("QUANTAI_ENV", os.getenv("ENV", "")).lower()
    if env == "production":
        return []
    return ["*"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    manager.start_background(asyncio.get_running_loop())
    logger.info("Dashboard WebSocket broadcaster started on /ws/live")
    yield


def create_app() -> FastAPI | None:
    """Create FastAPI dashboard app with REST, WebSocket, and static SPA."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        logger.warning("FastAPI not installed — dashboard unavailable")
        return None

    app = FastAPI(title="QuantAI Dashboard", version="2.0.0", lifespan=_lifespan)
    cors_origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["https://localhost"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    auth_token = dashboard_auth_token()
    env = os.getenv("QUANTAI_ENV", os.getenv("ENV", "")).lower()
    if not auth_token and env == "production":
        logger.warning(
            "DASHBOARD_AUTH_TOKEN is unset in production — dashboard API routes are unauthenticated"
        )
    if auth_token:
        from starlette.middleware.base import BaseHTTPMiddleware

        class DashboardAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                path = request.url.path
                if path.startswith("/api"):
                    if not is_dashboard_authorized(
                        authorization=request.headers.get("Authorization", ""),
                        query_token=request.query_params.get("token", ""),
                        header_token=request.headers.get("X-Dashboard-Token", ""),
                    ):
                        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
                return await call_next(request)

        app.add_middleware(DashboardAuthMiddleware)

    app.include_router(status.router)
    app.include_router(control.router)
    app.include_router(competition.router)
    app.include_router(integrations.router)
    app.include_router(notion.router)
    app.include_router(operator.router)
    app.include_router(demo.router)
    app.include_router(trades.router)
    app.include_router(positions.router)
    app.include_router(agents.router)
    app.include_router(risk.router)
    app.include_router(copilot.router)
    app.include_router(memory.router)
    app.include_router(adaptation.router)
    app.include_router(instruments.router)
    app.include_router(market.router)
    app.include_router(intelligence.router)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket)

    @app.get("/health")
    def health():
        return {"status": "ok"}

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

    from src.utils.logger import is_logfire_active, setup_logging

    if not is_logfire_active() and os.getenv("DASHBOARD_NO_LOGFIRE", "").lower() not in ("1", "true"):
        setup_logging(level=os.getenv("LOG_LEVEL", "INFO"), enable_logfire=True)

    app = create_app()
    if app is None:
        logger.error("Cannot start dashboard — install fastapi and uvicorn")
        return
    import uvicorn

    uvicorn.run(app, host=host, port=port)
