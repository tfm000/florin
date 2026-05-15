"""
Watchlist CRUD API — add, list, update, and remove watched assets.

All endpoints use Pydantic response models and FastAPI Depends() for DI.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from core.events import EventBus, EventType
from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import get_db_session, get_event_bus_dep, get_yfinance_dep
from dashboard.schemas import PaginatedResponse, SuccessResponse
from db.models import WatchlistORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["watchlist"])


# =============================================================================
# Request / Response schemas
# =============================================================================


class WatchlistItem(BaseModel):
    id: str
    ticker: str
    name: str
    asset_type: str
    notes: str
    added_at: datetime


class WatchlistAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)
    notes: str = ""
    asset_type: str = "equity"


class WatchlistUpdateRequest(BaseModel):
    notes: str


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/watchlist", response_model=PaginatedResponse[WatchlistItem])
async def list_watchlist(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session=Depends(get_db_session),
):
    """List all watched assets with pagination."""
    # Total count
    count_result = await session.execute(select(func.count(WatchlistORM.id)))
    total = count_result.scalar() or 0

    # Paginated items
    query = select(WatchlistORM).order_by(WatchlistORM.added_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    items = [
        WatchlistItem(
            id=r.id,
            ticker=r.ticker,
            name=r.name,
            asset_type=r.asset_type,
            notes=r.notes,
            added_at=r.added_at,
        )
        for r in rows
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


@router.post("/watchlist", response_model=WatchlistItem, status_code=201)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
    event_bus: EventBus = Depends(get_event_bus_dep),
):
    """Add a ticker to the watchlist. Returns 409 if already present."""
    ticker = req.ticker.upper()

    # Check for duplicates
    existing = await session.execute(select(WatchlistORM).where(WatchlistORM.ticker == ticker))
    if existing.scalar():
        raise ConflictError(f"{ticker} is already in your watchlist")

    # Auto-populate name from yfinance
    name = ""
    try:
        info = await yf.get_info(ticker)
        name = info.get("name", "")
    except Exception:
        logger.debug("Could not fetch name for %s", ticker)

    row = WatchlistORM(
        ticker=ticker,
        name=name,
        asset_type=req.asset_type,
        notes=req.notes,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        EventType.WATCHLIST_UPDATE,
        {"action": "added", "ticker": ticker},
        source="watchlist_api",
    )

    return WatchlistItem(
        id=row.id,
        ticker=row.ticker,
        name=row.name,
        asset_type=row.asset_type,
        notes=row.notes,
        added_at=row.added_at,
    )


@router.put("/watchlist/{ticker}", response_model=WatchlistItem)
async def update_watchlist_item(
    ticker: str,
    req: WatchlistUpdateRequest,
    session=Depends(get_db_session),
):
    """Update notes on a watchlist item."""
    ticker = ticker.upper()
    result = await session.execute(select(WatchlistORM).where(WatchlistORM.ticker == ticker))
    row = result.scalar()
    if not row:
        raise NotFoundError(f"{ticker} not found in watchlist")

    row.notes = req.notes
    await session.commit()
    await session.refresh(row)

    return WatchlistItem(
        id=row.id,
        ticker=row.ticker,
        name=row.name,
        asset_type=row.asset_type,
        notes=row.notes,
        added_at=row.added_at,
    )


@router.delete("/watchlist/{ticker}", response_model=SuccessResponse)
async def remove_from_watchlist(
    ticker: str,
    session=Depends(get_db_session),
    event_bus: EventBus = Depends(get_event_bus_dep),
):
    """Remove a ticker from the watchlist."""
    ticker = ticker.upper()
    result = await session.execute(select(WatchlistORM).where(WatchlistORM.ticker == ticker))
    row = result.scalar()
    if not row:
        raise NotFoundError(f"{ticker} not found in watchlist")

    await session.delete(row)
    await session.commit()

    await event_bus.publish(
        EventType.WATCHLIST_UPDATE,
        {"action": "removed", "ticker": ticker},
        source="watchlist_api",
    )

    return SuccessResponse()
