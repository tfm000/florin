"""Health check endpoint."""

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


@router.get("/health")
async def health_check() -> dict:
    """Return component health status and pipeline readiness."""
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
    if broker:
        try:
            broker_ok = await broker.health_check()
            broker_name = broker.name
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
        {
            "key": "fmp_api_key",
            "label": "FMP API Key (optional)",
            "description": "Optional. Enriches stocks with market cap, sector, and industry data.",
            "configured": bool(settings.fmp_api_key),
            "optional": True,
        },
    ]

    all_configured = all(
        item["configured"] for item in checklist if not item.get("optional")
    )

    if not db_ok:
        status = "degraded"
    elif not all_configured:
        status = "setup_required"
    else:
        status = "ok"

    return {
        "status": status,
        "database": db_ok,
        "broker": {"connected": broker_ok, "name": broker_name},
        "market_data": {
            "alpaca_configured": settings.alpaca_configured,
            "alpaca_connected": data_provider is not None,
        },
        "universe": {
            "fmp_configured": bool(settings.fmp_api_key),
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
