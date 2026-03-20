"""
Live Monitor API — add/remove/list assets for real-time price monitoring.

Monitored assets are subscribed to Alpaca WebSocket for live price updates.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from core.events import EventBus, EventType
from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import (
    get_data_provider_dep,
    get_db_session,
    get_event_bus_dep,
    get_yfinance_dep,
)
from dashboard.deps import get_data_provider
from dashboard.schemas import PaginatedResponse, SuccessResponse
from db.models import MonitoredAssetORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitor"])


# =============================================================================
# Response schemas
# =============================================================================

class MonitoredAssetResponse(BaseModel):
    id: str
    ticker: str
    name: str
    source: str
    asset_type: str
    is_active: bool
    added_at: datetime
    # Live data (joined from price cache)
    current_price: float | None = None
    change_pct: float | None = None
    volume: int | None = None


class MonitorAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/monitor", response_model=PaginatedResponse[MonitoredAssetResponse])
async def list_monitored(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session=Depends(get_db_session),
):
    """List monitored assets with live price data from Alpaca cache."""
    # Total count
    count_result = await session.execute(
        select(func.count(MonitoredAssetORM.id)).where(MonitoredAssetORM.is_active.is_(True))
    )
    total = count_result.scalar() or 0

    # Paginated items
    query = (
        select(MonitoredAssetORM)
        .where(MonitoredAssetORM.is_active.is_(True))
        .order_by(MonitoredAssetORM.added_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    rows = result.scalars().all()

    # Join with live price data from Alpaca cache
    data_provider = get_data_provider()
    price_cache = {}
    if data_provider and hasattr(data_provider, "cache"):
        price_cache = data_provider.cache

    items = []
    for r in rows:
        cached = price_cache.get(r.ticker, {})
        items.append(MonitoredAssetResponse(
            id=r.id,
            ticker=r.ticker,
            name=r.name,
            source=r.source,
            asset_type=r.asset_type,
            is_active=r.is_active,
            added_at=r.added_at,
            current_price=cached.get("price") or cached.get("close"),
            change_pct=cached.get("change_pct"),
            volume=cached.get("volume"),
        ))

    return PaginatedResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


@router.post("/monitor", response_model=MonitoredAssetResponse, status_code=201)
async def add_monitored(
    req: MonitorAddRequest,
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
    event_bus: EventBus = Depends(get_event_bus_dep),
):
    """Add a ticker for live monitoring. Returns 409 if already monitored."""
    ticker = req.ticker.upper()

    # Check for duplicates
    existing = await session.execute(
        select(MonitoredAssetORM).where(MonitoredAssetORM.ticker == ticker)
    )
    row = existing.scalar()
    if row:
        if row.is_active:
            raise ConflictError(f"{ticker} is already being monitored")
        # Re-activate if previously deactivated
        row.is_active = True
        await session.commit()
        await session.refresh(row)
    else:
        # Auto-populate name from yfinance
        name = ""
        try:
            info = await yf.get_info(ticker)
            name = info.get("name", "")
        except Exception:
            logger.debug("Could not fetch name for %s", ticker)

        row = MonitoredAssetORM(
            ticker=ticker,
            name=name,
            source="manual",
            asset_type="equity",
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    # Subscribe to Alpaca WebSocket if data provider available
    data_provider = get_data_provider()
    if data_provider and hasattr(data_provider, "update_subscriptions"):
        try:
            await data_provider.update_subscriptions([ticker])
        except Exception:
            logger.debug("Could not subscribe %s to Alpaca WebSocket", ticker)

    await event_bus.publish(
        EventType.MONITOR_UPDATE,
        {"action": "added", "ticker": ticker},
        source="monitor_api",
    )

    return MonitoredAssetResponse(
        id=row.id,
        ticker=row.ticker,
        name=row.name,
        source=row.source,
        asset_type=row.asset_type,
        is_active=row.is_active,
        added_at=row.added_at,
    )


@router.delete("/monitor/{ticker}", response_model=SuccessResponse)
async def remove_monitored(
    ticker: str,
    session=Depends(get_db_session),
    event_bus: EventBus = Depends(get_event_bus_dep),
):
    """Stop monitoring a ticker."""
    ticker = ticker.upper()
    result = await session.execute(
        select(MonitoredAssetORM).where(MonitoredAssetORM.ticker == ticker)
    )
    row = result.scalar()
    if not row:
        raise NotFoundError(f"{ticker} is not being monitored")

    row.is_active = False
    await session.commit()

    await event_bus.publish(
        EventType.MONITOR_UPDATE,
        {"action": "removed", "ticker": ticker},
        source="monitor_api",
    )

    return SuccessResponse()
