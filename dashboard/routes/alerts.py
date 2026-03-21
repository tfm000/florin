"""Price alert CRUD API."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.exceptions import NotFoundError
from dashboard.dependencies import get_db_session
from dashboard.schemas import SuccessResponse
from db.models import PriceAlertORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])


class PriceAlertCreate(BaseModel):
    ticker: str = Field(..., min_length=1)
    direction: str = Field(..., pattern="^(above|below)$")
    target_price: float = Field(..., gt=0)


class PriceAlertResponse(BaseModel):
    id: str
    ticker: str
    direction: str
    target_price: float
    is_active: bool
    triggered: bool
    created_at: str


@router.get("/alerts", response_model=list[PriceAlertResponse])
async def list_alerts(
    active_only: bool = Query(default=True),
    session=Depends(get_db_session),
):
    query = select(PriceAlertORM).order_by(PriceAlertORM.created_at.desc())
    if active_only:
        query = query.where(PriceAlertORM.is_active.is_(True))
    result = await session.execute(query)
    return [
        PriceAlertResponse(
            id=a.id, ticker=a.ticker, direction=a.direction,
            target_price=a.target_price, is_active=a.is_active,
            triggered=a.triggered, created_at=str(a.created_at),
        )
        for a in result.scalars().all()
    ]


@router.post("/alerts", response_model=PriceAlertResponse, status_code=201)
async def create_alert(req: PriceAlertCreate, session=Depends(get_db_session)):
    alert = PriceAlertORM(
        ticker=req.ticker.upper(),
        direction=req.direction,
        target_price=req.target_price,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return PriceAlertResponse(
        id=alert.id, ticker=alert.ticker, direction=alert.direction,
        target_price=alert.target_price, is_active=alert.is_active,
        triggered=alert.triggered, created_at=str(alert.created_at),
    )


@router.delete("/alerts/{alert_id}", response_model=SuccessResponse)
async def delete_alert(alert_id: str, session=Depends(get_db_session)):
    result = await session.execute(select(PriceAlertORM).where(PriceAlertORM.id == alert_id))
    alert = result.scalar()
    if not alert:
        raise NotFoundError("Alert not found")
    await session.delete(alert)
    await session.commit()
    return SuccessResponse()
