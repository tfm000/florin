"""GET /api/positions — Open positions with live P&L."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.deps import get_broker

router = APIRouter(tags=["positions"])


@router.get("/positions")
async def get_positions():
    """Get all open positions with unrealised P&L."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")
    positions = await broker.get_positions()
    return [p.model_dump() for p in positions]


@router.get("/positions/{ticker}")
async def get_position(ticker: str):
    """Get a specific position by ticker."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")
    position = await broker.get_position(ticker.upper())
    if not position:
        raise HTTPException(404, f"No position for {ticker}")
    return position.model_dump()
