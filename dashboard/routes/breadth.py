"""Market breadth indicators — live + historical from DB snapshots.

Falls back to live computation via the screener engine when no DB snapshots exist.
Supports exchange selection via query parameter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from dashboard.dependencies import get_db_session, get_yfinance_dep
from db.models import BreadthSnapshotORM
from scanner.breadth_scanner import DEFAULT_EXCHANGES, compute_breadth

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


@router.get("/breadth", response_model=BreadthResponse)
async def get_market_breadth(
    exchange: str = Query(
        default=DEFAULT_EXCHANGES,
        description="Comma-separated exchange codes (e.g. NMS,NGM,NCM,NYQ)",
    ),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Latest market breadth — from DB snapshot or live computation.

    When exchange differs from the default, always computes live
    (DB snapshots only store the default exchange set).
    """
    is_default = exchange == DEFAULT_EXCHANGES

    if is_default:
        result = await session.execute(
            select(BreadthSnapshotORM)
            .order_by(BreadthSnapshotORM.recorded_at.desc())
            .limit(1)
        )
        latest = result.scalar()

        if latest:
            total = latest.total
            return BreadthResponse(
                advancing=latest.advancing,
                declining=latest.declining,
                unchanged=latest.unchanged,
                advance_decline_ratio=latest.ad_ratio,
                total_stocks=total,
                pct_advancing=round(latest.advancing / total * 100, 1) if total > 0 else 0,
            )

    # Live computation (either no DB snapshot or non-default exchanges)
    data = await compute_breadth([], exchange=exchange)
    total = data["total"]
    if total == 0:
        return BreadthResponse()

    return BreadthResponse(
        advancing=data["advancing"],
        declining=data["declining"],
        unchanged=data["unchanged"],
        advance_decline_ratio=data["ad_ratio"],
        total_stocks=total,
        pct_advancing=round(data["advancing"] / total * 100, 1),
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
