"""Health check endpoints — liveness, readiness, and combined."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from dashboard.deps import (
    get_broker,
    get_data_provider,
    get_db,
    get_scanner,
    get_settings,
    get_shutdown_callback,
    get_universe,
)

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict:
    """Liveness probe — is the process alive? Always returns 200."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict:
    """Readiness probe — are all critical dependencies healthy?"""
    db = get_db()
    broker = get_broker()

    db_ok = False
    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    broker_ok = False
    if broker:
        try:
            broker_ok = await broker.health_check()
        except Exception:
            pass

    ready = db_ok and broker_ok
    return {
        "status": "ready" if ready else "not_ready",
        "database": db_ok,
        "broker": broker_ok,
    }


@router.get("/health")
async def health_check() -> dict:
    """Return component health status, pipeline readiness, and trading mode."""
    settings = get_settings()
    db = get_db()
    broker = get_broker()
    universe = get_universe()
    scanner = get_scanner()
    data_provider = get_data_provider()

    # Database
    db_ok = False
    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Broker
    broker_ok = False
    broker_name = None
    broker_is_live = False
    if broker:
        try:
            broker_ok = await broker.health_check()
            broker_name = broker.name
            broker_is_live = broker.is_live
        except Exception:
            pass

    # Universe
    universe_size = universe.size if universe else 0
    universe_refresh = None
    if universe and universe.last_refresh:
        universe_refresh = universe.last_refresh.isoformat()

    # Setup checklist — tells the frontend what's missing
    checklist = [
        {
            "key": "alpaca",
            "label": "Alpaca API",
            "description": "Required for stock universe discovery, real-time market data, and price streaming.",
            "configured": settings.alpaca_configured,
        },
    ]

    all_configured = all(item["configured"] for item in checklist)

    if not db_ok:
        status = "degraded"
    elif not all_configured:
        status = "setup_required"
    else:
        status = "ok"

    return {
        "status": status,
        "paper_trading": settings.paper_trading,
        "trading_mode": "PAPER" if settings.paper_trading else "LIVE",
        "database": db_ok,
        "broker": {
            "connected": broker_ok,
            "name": broker_name,
            "is_live": broker_is_live,
        },
        "market_data": {
            "alpaca_configured": settings.alpaca_configured,
            "alpaca_connected": data_provider is not None,
        },
        "universe": {
            "ticker_count": universe_size,
            "last_refresh": universe_refresh,
        },
        "scanner": {
            "active": scanner is not None,
        },
        "telegram_configured": settings.telegram_configured,
        "setup_checklist": checklist,
    }


@router.post("/terminate")
async def terminate() -> dict:
    """Gracefully shut down the Sentinel application."""
    import asyncio

    shutdown = get_shutdown_callback()
    if not shutdown:
        return {"status": "no shutdown handler registered"}

    # Schedule shutdown after response is sent
    asyncio.get_event_loop().call_later(0.5, shutdown)
    return {"status": "shutting_down"}
