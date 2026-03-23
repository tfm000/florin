"""
Multi-factor stock screener with saved filter presets.

Uses the shared screener engine for query execution.
Supports momentum-based post-filtering and saved screener configurations.
Includes alert management endpoints for the ScreenerAlertService.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import get_db_session, get_yfinance_dep
from dashboard.services.screener_engine import (
    ScreenerResponse,
    apply_momentum_filter,
    run_screen,
)
from db.models import SavedScreenerORM, ScreenerAlertLogORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["screener"])


# ── Main screener endpoint ───────────────────────────────────────────────────


@router.get("/screener", response_model=ScreenerResponse)
async def screen_stocks(
    price_min: float = Query(default=0, ge=0),
    price_max: float = Query(default=0, ge=0, description="0 = no limit"),
    market_cap_min: float = Query(default=0, ge=0),
    market_cap_max: float = Query(default=0, ge=0, description="0 = no limit"),
    pe_min: float = Query(default=0),
    pe_max: float = Query(default=0, description="0 = no limit"),
    dividend_yield_min: float = Query(default=0, ge=0),
    sector: str = Query(default="", description="Filter by sector name"),
    exchange: str = Query(default="", description="NMS, NGM, NCM, NYQ, ASE or comma-separated"),
    asset_type: str = Query(default="", description="EQUITY, ETF, INDEX, COMMODITY, CRYPTOCURRENCY"),
    momentum_min: float = Query(default=0, description="Min return % for momentum filter"),
    momentum_max: float = Query(default=0, description="Max return % (0 = no limit)"),
    momentum_period: str = Query(default="", description="1d, 5d, 1w, 1mo, 3mo, 1y"),
    sort_by: str = Query(default="intradaymarketcap", description="Sort field"),
    sort_asc: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=250),
    yf=Depends(get_yfinance_dep),
):
    """General-purpose multi-factor stock screener with momentum filtering."""
    results = await run_screen(
        price_min=price_min, price_max=price_max,
        market_cap_min=market_cap_min, market_cap_max=market_cap_max,
        pe_min=pe_min, pe_max=pe_max,
        dividend_yield_min=dividend_yield_min,
        sector=sector, exchange=exchange, asset_type=asset_type,
        sort_by=sort_by, sort_asc=sort_asc, limit=limit, yf=yf,
    )

    # Apply momentum post-filter if requested
    if momentum_period and (momentum_min > 0 or momentum_max > 0):
        results = await apply_momentum_filter(
            results, momentum_min, momentum_max, momentum_period, yf,
        )

    return ScreenerResponse(total=len(results), results=results)


# ── Saved screener CRUD ──────────────────────────────────────────────────────


class SavedScreenerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    filters: dict[str, Any]
    sort_by: str = "intradaymarketcap"
    sort_asc: bool = False


class SavedScreenerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    filters: dict[str, Any] | None = None
    sort_by: str | None = None
    sort_asc: bool | None = None


class SavedScreenerResponse(BaseModel):
    id: str
    name: str
    filters: dict[str, Any]
    sort_by: str
    sort_asc: bool
    is_alert_active: bool
    max_alerts_per_day: int
    include_llm_report: bool
    run_interval_seconds: int
    last_run_at: str | None
    created_at: str
    updated_at: str


def _orm_to_response(orm: SavedScreenerORM) -> SavedScreenerResponse:
    return SavedScreenerResponse(
        id=orm.id,
        name=orm.name,
        filters=json.loads(orm.filters_json),
        sort_by=orm.sort_by,
        sort_asc=orm.sort_asc,
        is_alert_active=orm.is_alert_active,
        max_alerts_per_day=orm.max_alerts_per_day,
        include_llm_report=orm.include_llm_report,
        run_interval_seconds=orm.run_interval_seconds,
        last_run_at=str(orm.last_run_at) if orm.last_run_at else None,
        created_at=str(orm.created_at),
        updated_at=str(orm.updated_at),
    )


@router.get("/screener/saved", response_model=list[SavedScreenerResponse])
async def list_saved_screeners(session=Depends(get_db_session)):
    """List all saved screener configurations."""
    result = await session.execute(
        select(SavedScreenerORM).order_by(SavedScreenerORM.created_at.desc())
    )
    return [_orm_to_response(s) for s in result.scalars().all()]


@router.get("/screener/saved/{screener_id}", response_model=SavedScreenerResponse)
async def get_saved_screener(screener_id: str, session=Depends(get_db_session)):
    """Get a single saved screener by ID."""
    result = await session.execute(
        select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
    )
    orm = result.scalar()
    if not orm:
        raise NotFoundError("Saved screener not found")
    return _orm_to_response(orm)


@router.post("/screener/saved", response_model=SavedScreenerResponse, status_code=201)
async def create_saved_screener(
    req: SavedScreenerCreate,
    session=Depends(get_db_session),
):
    """Save a new screener configuration."""
    # Check uniqueness
    existing = await session.execute(
        select(SavedScreenerORM).where(SavedScreenerORM.name == req.name)
    )
    if existing.scalar():
        raise ConflictError(f"Screener '{req.name}' already exists")

    now = datetime.now(UTC)
    orm = SavedScreenerORM(
        name=req.name,
        filters_json=json.dumps(req.filters),
        sort_by=req.sort_by,
        sort_asc=req.sort_asc,
        created_at=now,
        updated_at=now,
    )
    session.add(orm)
    await session.commit()
    await session.refresh(orm)
    return _orm_to_response(orm)


@router.put("/screener/saved/{screener_id}", response_model=SavedScreenerResponse)
async def update_saved_screener(
    screener_id: str,
    req: SavedScreenerUpdate,
    session=Depends(get_db_session),
):
    """Update an existing saved screener."""
    result = await session.execute(
        select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
    )
    orm = result.scalar()
    if not orm:
        raise NotFoundError("Saved screener not found")

    if req.name is not None:
        # Check uniqueness if name is changing
        if req.name != orm.name:
            dup = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.name == req.name)
            )
            if dup.scalar():
                raise ConflictError(f"Screener '{req.name}' already exists")
        orm.name = req.name
    if req.filters is not None:
        orm.filters_json = json.dumps(req.filters)
    if req.sort_by is not None:
        orm.sort_by = req.sort_by
    if req.sort_asc is not None:
        orm.sort_asc = req.sort_asc

    orm.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(orm)
    return _orm_to_response(orm)


@router.delete("/screener/saved/{screener_id}")
async def delete_saved_screener(screener_id: str, session=Depends(get_db_session)):
    """Delete a saved screener."""
    result = await session.execute(
        select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
    )
    orm = result.scalar()
    if not orm:
        raise NotFoundError("Saved screener not found")

    await session.delete(orm)
    await session.commit()
    return {"deleted": screener_id}


# ── Alert management endpoints ────────────────────────────────────────────────


class AlertSettingsUpdate(BaseModel):
    """Update alert-related settings on a saved screener."""
    is_alert_active: bool | None = None
    max_alerts_per_day: int | None = Field(None, ge=1, le=100)
    run_interval_seconds: int | None = Field(None, ge=60, le=86400)
    include_llm_report: bool | None = None


class ScreenerAlertLogResponse(BaseModel):
    """Single entry in the screener alert log."""
    id: str
    screener_id: str
    ticker: str
    price: float | None
    change_pct: float | None
    alert_data: dict[str, Any]
    sent_at: str


@router.put("/screener/saved/{screener_id}/alerts", response_model=SavedScreenerResponse)
async def update_alert_settings(
    screener_id: str,
    req: AlertSettingsUpdate,
    session=Depends(get_db_session),
):
    """Update alert settings (activate/deactivate, interval, max per day, LLM toggle)."""
    result = await session.execute(
        select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
    )
    orm = result.scalar()
    if not orm:
        raise NotFoundError("Saved screener not found")

    if req.is_alert_active is not None:
        orm.is_alert_active = req.is_alert_active
    if req.max_alerts_per_day is not None:
        orm.max_alerts_per_day = req.max_alerts_per_day
    if req.run_interval_seconds is not None:
        orm.run_interval_seconds = req.run_interval_seconds
    if req.include_llm_report is not None:
        orm.include_llm_report = req.include_llm_report

    orm.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(orm)
    return _orm_to_response(orm)


@router.get(
    "/screener/saved/{screener_id}/alerts",
    response_model=list[ScreenerAlertLogResponse],
)
async def get_alert_log(
    screener_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    session=Depends(get_db_session),
):
    """Get recent alert log entries for a saved screener."""
    # Verify screener exists
    screener_result = await session.execute(
        select(SavedScreenerORM.id).where(SavedScreenerORM.id == screener_id)
    )
    if not screener_result.scalar():
        raise NotFoundError("Saved screener not found")

    result = await session.execute(
        select(ScreenerAlertLogORM)
        .where(ScreenerAlertLogORM.screener_id == screener_id)
        .order_by(ScreenerAlertLogORM.sent_at.desc())
        .limit(limit)
    )

    return [
        ScreenerAlertLogResponse(
            id=log.id,
            screener_id=log.screener_id,
            ticker=log.ticker,
            price=log.price,
            change_pct=log.change_pct,
            alert_data=json.loads(log.alert_data_json),
            sent_at=str(log.sent_at),
        )
        for log in result.scalars().all()
    ]
