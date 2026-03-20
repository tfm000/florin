"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from dashboard.deps import get_broker, get_db, get_settings, get_shutdown_callback

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Return component health status."""
    settings = get_settings()
    db = get_db()
    broker = get_broker()

    # Database
    db_ok = False
    try:
        async with db.session() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
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

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "broker": {"connected": broker_ok, "name": broker_name},
        "alpaca_configured": settings.alpaca_configured,
        "telegram_configured": settings.telegram_configured,
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
