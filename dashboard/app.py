"""
FastAPI dashboard application.

Serves REST API + WebSocket for real-time updates.
In production, also serves the built React frontend as static files.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import Settings
from core.events import EventBus
from db.database import Database
from dashboard.deps import set_state
from dashboard.ws import ConnectionManager

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    db: Database,
    event_bus: EventBus,
    broker=None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    set_state("settings", settings)
    set_state("db", db)
    set_state("event_bus", event_bus)
    set_state("broker", broker)
    set_state("ws_manager", ConnectionManager())

    app = FastAPI(
        title="Penny Stock Sentinel",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # CORS — allow React dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes (import here to avoid circular imports)
    from dashboard.routes import positions, universe, reports, trades, account, orders, stats

    app.include_router(positions.router, prefix="/api")
    app.include_router(universe.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(trades.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(orders.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")

    # WebSocket endpoint
    from dashboard.ws import websocket_endpoint
    app.add_api_websocket_route("/ws", websocket_endpoint)

    # Serve React build if it exists
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    logger.info("Dashboard app created")
    return app


async def serve(app: FastAPI, settings: Settings) -> None:
    """Run the dashboard server (called from main.py)."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
