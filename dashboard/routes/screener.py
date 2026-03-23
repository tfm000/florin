"""
Multi-factor stock screener with saved filter presets.

Uses yfinance's EquityQuery + screen() API for server-side filtering.
Supports momentum-based post-filtering and saved screener configurations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import get_db_session, get_yfinance_dep
from db.models import SavedScreenerORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["screener"])

# ── Screener response models ─────────────────────────────────────────────────


class ScreenerResult(BaseModel):
    ticker: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    price: float | None = None
    volume: int | None = None
    avg_volume: int | None = None
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    change_pct: float | None = None


class ScreenerResponse(BaseModel):
    total: int
    results: list[ScreenerResult]


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
    results = await _run_screen(
        price_min=price_min, price_max=price_max,
        market_cap_min=market_cap_min, market_cap_max=market_cap_max,
        pe_min=pe_min, pe_max=pe_max,
        dividend_yield_min=dividend_yield_min,
        sector=sector, exchange=exchange, asset_type=asset_type,
        sort_by=sort_by, sort_asc=sort_asc, limit=limit, yf=yf,
    )

    # Apply momentum post-filter if requested
    if momentum_period and (momentum_min > 0 or momentum_max > 0):
        results = await _apply_momentum_filter(
            results, momentum_min, momentum_max, momentum_period, yf,
        )

    return ScreenerResponse(total=len(results), results=results)


async def _run_screen(
    *,
    price_min: float, price_max: float,
    market_cap_min: float, market_cap_max: float,
    pe_min: float, pe_max: float,
    dividend_yield_min: float,
    sector: str, exchange: str, asset_type: str,
    sort_by: str, sort_asc: bool, limit: int,
    yf: Any,
) -> list[ScreenerResult]:
    """Execute the yfinance screen query. Runs in a thread."""

    def _screen() -> list[ScreenerResult]:
        try:
            from yfinance import EquityQuery, screen

            operands = [
                EquityQuery("eq", ["region", "us"]),
            ]

            if price_min > 0:
                operands.append(EquityQuery("gt", ["intradayprice", price_min]))
            if price_max > 0:
                operands.append(EquityQuery("lt", ["intradayprice", price_max]))
            if market_cap_min > 0:
                operands.append(EquityQuery("gt", ["intradaymarketcap", market_cap_min]))
            if market_cap_max > 0:
                operands.append(EquityQuery("lt", ["intradaymarketcap", market_cap_max]))
            if pe_min > 0:
                operands.append(EquityQuery("gt", ["trailingpe", pe_min]))
            if pe_max > 0:
                operands.append(EquityQuery("lt", ["trailingpe", pe_max]))
            if dividend_yield_min > 0:
                operands.append(EquityQuery("gt", ["dividendyield", dividend_yield_min / 100]))
            if sector:
                operands.append(EquityQuery("eq", ["sector", sector]))

            # Exchange filter
            if exchange:
                exchanges = [e.strip() for e in exchange.split(",")]
                if len(exchanges) == 1:
                    operands.append(EquityQuery("eq", ["exchange", exchanges[0]]))
                else:
                    operands.append(EquityQuery("or", [
                        EquityQuery("eq", ["exchange", e]) for e in exchanges
                    ]))

            if len(operands) < 2:
                operands.append(EquityQuery("gt", ["intradayprice", 0]))
            query = EquityQuery("and", operands)
            resp = screen(query, size=limit, offset=0,
                          sortField=sort_by, sortAsc=sort_asc)

            quotes = resp.get("quotes", []) if resp else []

            results = []
            for q in quotes:
                # Apply asset type filter (post-screen, yfinance doesn't support quoteType in EquityQuery)
                if asset_type:
                    qt = q.get("quoteType", "EQUITY")
                    if qt.upper() != asset_type.upper():
                        continue

                results.append(ScreenerResult(
                    ticker=q.get("symbol", ""),
                    name=q.get("shortName") or q.get("longName", ""),
                    exchange=q.get("exchange", ""),
                    sector=q.get("sector", ""),
                    industry=q.get("industry", ""),
                    market_cap=q.get("marketCap"),
                    price=q.get("regularMarketPrice"),
                    volume=q.get("regularMarketVolume"),
                    avg_volume=q.get("averageDailyVolume3Month"),
                    pe_ratio=q.get("trailingPE"),
                    dividend_yield=q.get("dividendYield"),
                    change_pct=q.get("regularMarketChangePercent"),
                ))

            return results

        except Exception:
            logger.exception("Screener query failed")
            return []

    return await asyncio.to_thread(_screen)


async def _apply_momentum_filter(
    results: list[ScreenerResult],
    momentum_min: float,
    momentum_max: float,
    period: str,
    yf: Any,
) -> list[ScreenerResult]:
    """Post-filter screener results by return momentum over a given period.

    Fetches historical data for the first 100 results to limit latency,
    then filters to those within [momentum_min, momentum_max].
    """
    # Map period labels to yfinance format
    period_map = {
        "1d": "5d", "5d": "1mo", "1w": "1mo",
        "1mo": "1mo", "3mo": "3mo", "1y": "1y",
    }
    yf_period = period_map.get(period, "1mo")

    # Day counts for return calculation
    day_counts = {
        "1d": 1, "5d": 5, "1w": 5,
        "1mo": 21, "3mo": 63, "1y": 252,
    }
    days = day_counts.get(period, 21)

    # Limit to first 100 to keep latency reasonable
    candidates = results[:100]
    if not candidates:
        return []

    # Fetch histories concurrently
    async def _get_return(item: ScreenerResult) -> tuple[ScreenerResult, float | None]:
        try:
            hist = await yf.get_history(item.ticker, period=yf_period)
            if not hist or len(hist) <= days:
                return item, None
            closes = [h["close"] for h in hist if h.get("close") and h["close"] > 0]
            if len(closes) <= days:
                return item, None
            ret = (closes[-1] / closes[-(days + 1)] - 1) * 100
            return item, ret
        except Exception:
            return item, None

    pairs = await asyncio.gather(*[_get_return(r) for r in candidates])

    filtered = []
    for item, ret in pairs:
        if ret is None:
            continue
        if momentum_min > 0 and ret < momentum_min:
            continue
        if momentum_max > 0 and ret > momentum_max:
            continue
        filtered.append(item)

    return filtered


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
