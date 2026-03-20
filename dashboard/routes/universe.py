"""GET /api/universe — Penny stock universe and scanner settings."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from dashboard.deps import get_data_provider, get_db, get_settings
from dashboard.schemas import PaginatedResponse
from db.models import MonitoredAssetORM, UniverseStockORM

router = APIRouter(tags=["universe"])


class UniverseStockResponse(BaseModel):
    ticker: str
    name: str
    exchange: str
    t212_ticker: str
    sector: str
    industry: str
    market_cap: float | None
    shares_outstanding: int | None = None
    inferred_market_cap: float | None = None
    avg_volume: int
    last_price: float
    today_return: float | None = None
    is_monitored: bool = False
    in_universe: bool
    updated_at: str


@router.get("/universe", response_model=PaginatedResponse[UniverseStockResponse])
async def get_universe(
    in_universe: bool = True,
    exchange: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_market_cap: float | None = None,
    max_market_cap: float | None = None,
    sort_by: str = Query(default="ticker", pattern="^(ticker|today_return|market_cap|last_price)$"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    """Get penny stock universe with optional filters, pagination, and live data."""
    db = get_db()
    async with db.session() as session:
        # Base filter
        base_filter = []
        if in_universe:
            base_filter.append(UniverseStockORM.in_universe.is_(True))
        if exchange:
            base_filter.append(UniverseStockORM.exchange == exchange.upper())
        if min_price is not None:
            base_filter.append(UniverseStockORM.last_price >= min_price)
        if max_price is not None:
            base_filter.append(UniverseStockORM.last_price <= max_price)
        if min_market_cap is not None:
            base_filter.append(UniverseStockORM.market_cap >= min_market_cap)
        if max_market_cap is not None:
            base_filter.append(UniverseStockORM.market_cap <= max_market_cap)

        # Total count
        count_q = select(func.count(UniverseStockORM.ticker)).where(*base_filter)
        total = (await session.execute(count_q)).scalar() or 0

        # Paginated query
        query = select(UniverseStockORM).where(*base_filter)

        # Sort (today_return is computed post-query)
        if sort_by == "market_cap":
            query = query.order_by(UniverseStockORM.market_cap.desc().nullslast())
        elif sort_by == "last_price":
            query = query.order_by(UniverseStockORM.last_price.desc())
        else:
            query = query.order_by(UniverseStockORM.ticker)

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        stocks = result.scalars().all()

        # Get monitored tickers for is_monitored flag
        monitored_result = await session.execute(
            select(MonitoredAssetORM.ticker).where(MonitoredAssetORM.is_active.is_(True))
        )
        monitored_tickers = {r for r in monitored_result.scalars().all()}

    # Get live price data from Alpaca cache for today_return
    data_provider = get_data_provider()
    price_cache = {}
    if data_provider and hasattr(data_provider, "cache"):
        price_cache = data_provider.cache

    items = []
    for s in stocks:
        cached = price_cache.get(s.ticker)
        today_return = getattr(cached, "change_pct", None) if cached else None
        # Filter out implausible returns (bad data from corporate actions)
        if today_return is not None and abs(today_return) > 200:
            today_return = None

        items.append(UniverseStockResponse(
            ticker=s.ticker,
            name=s.name,
            exchange=s.exchange,
            t212_ticker=s.t212_ticker,
            sector=s.sector,
            industry=s.industry,
            market_cap=s.market_cap,
            shares_outstanding=s.shares_outstanding,
            inferred_market_cap=s.inferred_market_cap,
            avg_volume=s.avg_volume,
            last_price=getattr(cached, "price", None) or s.last_price,
            today_return=today_return,
            is_monitored=s.ticker in monitored_tickers,
            in_universe=s.in_universe,
            updated_at=str(s.updated_at),
        ))

    # Post-query sort by today_return if requested
    if sort_by == "today_return":
        items.sort(key=lambda x: x.today_return or -999, reverse=True)

    return PaginatedResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


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
        "price_min": settings.scan_price_min,
        "price_max": settings.scan_price_max,
        "market_cap_min": settings.scan_market_cap_min,
        "market_cap_max": settings.scan_market_cap_max,
        "momentum_threshold": settings.scan_momentum_threshold,
        "scan_interval_seconds": settings.scan_interval_seconds,
        "cooldown_minutes": settings.scan_cooldown_minutes,
        "min_volume": settings.scan_min_volume,
    }
