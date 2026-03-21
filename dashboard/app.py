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
from core.exceptions import SentinelError
from db.database import Database
from dashboard.deps import set_state
from dashboard.middleware import (
    RequestIdMiddleware,
    RateLimitMiddleware,
    sentinel_exception_handler,
)
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
        title="Sentinel Terminal",
        version="0.2.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # Exception handler for domain exceptions
    app.add_exception_handler(SentinelError, sentinel_exception_handler)

    # Middleware (applied bottom-to-top: RequestId runs first, then RateLimit, then CORS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # Register API routes (import here to avoid circular imports)
    from dashboard.routes import (
        positions, universe, reports, trades, account, orders,
        stats, health, settings, research, watchlist, monitor,
        calendar, screener, correlation, risk, filings_13f, portfolio,
        short_interest, breadth, news_feed, regime, alerts, insiders,
        market_hours,
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(research.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(monitor.router, prefix="/api")
    app.include_router(positions.router, prefix="/api")
    app.include_router(universe.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(trades.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(orders.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(calendar.router, prefix="/api")
    app.include_router(screener.router, prefix="/api")
    app.include_router(correlation.router, prefix="/api")
    app.include_router(risk.router, prefix="/api")
    app.include_router(filings_13f.router, prefix="/api")
    app.include_router(portfolio.router, prefix="/api")
    app.include_router(short_interest.router, prefix="/api")
    app.include_router(breadth.router, prefix="/api")
    app.include_router(news_feed.router, prefix="/api")
    app.include_router(regime.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")
    app.include_router(insiders.router, prefix="/api")
    app.include_router(market_hours.router, prefix="/api")

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
    import asyncio
    import webbrowser

    import uvicorn

    config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # Open browser once server is ready
    async def _open_browser() -> None:
        await asyncio.sleep(1.0)
        url = f"http://localhost:{settings.dashboard_port}"
        logger.info("Opening dashboard: %s", url)
        webbrowser.open(url)

    asyncio.create_task(_open_browser())
    await server.serve()
