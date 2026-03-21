"""Market breadth indicators — live + historical from DB snapshots.

Falls back to live yfinance computation when no DB snapshots exist.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from dashboard.dependencies import get_db_session, get_yfinance_dep
from db.models import BreadthSnapshotORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["breadth"])


class BreadthResponse(BaseModel):
    advancing: int = 0
    declining: int = 0
    unchanged: int = 0
    advance_decline_ratio: float = 0
    total_stocks: int = 0
    pct_advancing: float = 0


class BreadthHistoryPoint(BaseModel):
    date: str
    hour: int
    advancing: int
    declining: int
    total: int
    ad_ratio: float


class BreadthHistoryResponse(BaseModel):
    snapshots: list[BreadthHistoryPoint]


async def _live_breadth(yf) -> BreadthResponse:
    """Compute breadth on-the-fly from major index ETFs as a proxy."""

    def _compute():
        try:
            from yfinance import EquityQuery, screen

            query = EquityQuery("and", [
                EquityQuery("eq", ["region", "us"]),
                EquityQuery("or", [
                    EquityQuery("eq", ["exchange", "NMS"]),
                    EquityQuery("eq", ["exchange", "NGM"]),
                    EquityQuery("eq", ["exchange", "NCM"]),
                    EquityQuery("eq", ["exchange", "NYQ"]),
                    EquityQuery("eq", ["exchange", "ASE"]),
                ]),
                EquityQuery("gt", ["intradaymarketcap", 300_000_000]),
            ])

            advancing = 0
            declining = 0
            unchanged = 0
            offset = 0
            page_size = 250

            while offset < 4000:
                resp = screen(query, size=page_size, offset=offset,
                              sortField="intradaymarketcap", sortAsc=False)
                quotes = resp.get("quotes", []) if resp else []
                if not quotes:
                    break
                for q in quotes:
                    change = q.get("regularMarketChangePercent", 0) or 0
                    if change > 0.01:
                        advancing += 1
                    elif change < -0.01:
                        declining += 1
                    else:
                        unchanged += 1
                offset += page_size
                if len(quotes) < page_size:
                    break

            total = advancing + declining + unchanged
            if total == 0:
                return BreadthResponse()

            ad_ratio = advancing / declining if declining > 0 else (
                float(advancing) if advancing > 0 else 0
            )
            return BreadthResponse(
                advancing=advancing,
                declining=declining,
                unchanged=unchanged,
                advance_decline_ratio=round(ad_ratio, 2),
                total_stocks=total,
                pct_advancing=round(advancing / total * 100, 1),
            )
        except Exception:
            logger.exception("Live breadth computation failed")
            return BreadthResponse()

    return await asyncio.to_thread(_compute)


@router.get("/breadth", response_model=BreadthResponse)
async def get_market_breadth(
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Latest market breadth — from DB snapshot, falling back to live computation."""
    result = await session.execute(
        select(BreadthSnapshotORM)
        .order_by(BreadthSnapshotORM.recorded_at.desc())
        .limit(1)
    )
    latest = result.scalar()

    if not latest:
        return await _live_breadth(yf)

    total = latest.total
    return BreadthResponse(
        advancing=latest.advancing,
        declining=latest.declining,
        unchanged=latest.unchanged,
        advance_decline_ratio=latest.ad_ratio,
        total_stocks=total,
        pct_advancing=round(latest.advancing / total * 100, 1) if total > 0 else 0,
    )


@router.get("/breadth/history", response_model=BreadthHistoryResponse)
async def get_breadth_history(
    days: int = Query(default=30, ge=1, le=365),
    session=Depends(get_db_session),
):
    """Historical breadth snapshots for charting trends."""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = await session.execute(
        select(BreadthSnapshotORM)
        .where(BreadthSnapshotORM.date >= cutoff)
        .order_by(BreadthSnapshotORM.date, BreadthSnapshotORM.hour)
    )
    snapshots = result.scalars().all()

    return BreadthHistoryResponse(
        snapshots=[
            BreadthHistoryPoint(
                date=s.date,
                hour=s.hour,
                advancing=s.advancing,
                declining=s.declining,
                total=s.total,
                ad_ratio=s.ad_ratio,
            )
            for s in snapshots
        ]
    )
