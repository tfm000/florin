"""GET /api/account — Trading 212 account summary."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.deps import get_broker

router = APIRouter(tags=["account"])


@router.get("/account")
async def get_account():
    """Get broker account summary (cash, invested value, totals)."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")
    summary = await broker.get_account_summary()
    return summary.model_dump()
