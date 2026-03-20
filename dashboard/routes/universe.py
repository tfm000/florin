"""GET /api/universe — Penny stock universe and scanner settings."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from dashboard.deps import get_db, get_settings
from db.models import UniverseStockORM

router = APIRouter(tags=["universe"])


@router.get("/universe")
async def get_universe(
    in_universe: bool = True,
    exchange: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 500,
    offset: int = 0,
):
    """Get penny stock universe with optional filters."""
    db = get_db()
    async with db.session() as session:
        query = select(UniverseStockORM)

        if in_universe:
            query = query.where(UniverseStockORM.in_universe.is_(True))
        if exchange:
            query = query.where(UniverseStockORM.exchange == exchange.upper())
        if min_price is not None:
            query = query.where(UniverseStockORM.last_price >= min_price)
        if max_price is not None:
            query = query.where(UniverseStockORM.last_price <= max_price)

        query = query.order_by(UniverseStockORM.ticker).offset(offset).limit(limit)
        result = await session.execute(query)
        stocks = result.scalars().all()

    return [
        {
            "ticker": s.ticker,
            "name": s.name,
            "exchange": s.exchange,
            "t212_ticker": s.t212_ticker,
            "sector": s.sector,
            "industry": s.industry,
            "market_cap": s.market_cap,
            "avg_volume": s.avg_volume,
            "last_price": s.last_price,
            "in_universe": s.in_universe,
            "updated_at": str(s.updated_at),
        }
        for s in stocks
    ]


class ScannerSettingsUpdate(BaseModel):
    price_threshold: float | None = None
    momentum_threshold: float | None = None
    scan_interval_seconds: int | None = None
    min_volume: int | None = None


@router.get("/universe/settings")
async def get_scanner_settings():
    """Get current scanner configuration."""
    settings = get_settings()
    return {
        "price_threshold": settings.scan_price_threshold,
        "momentum_threshold": settings.scan_momentum_threshold,
        "scan_interval_seconds": settings.scan_interval_seconds,
        "cooldown_minutes": settings.scan_cooldown_minutes,
        "min_volume": settings.scan_min_volume,
    }
