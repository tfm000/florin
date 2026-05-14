"""GET /api/trades — Executed trade history."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import desc, select

from dashboard.deps import get_db
from db.models import TradeORM

router = APIRouter(tags=["trades"])


@router.get("/trades")
async def get_trades(
    ticker: str | None = None,
    side: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Get executed trade history with optional filters."""
    db = get_db()
    async with db.session() as session:
        query = select(TradeORM).order_by(desc(TradeORM.executed_at))

        if ticker:
            query = query.where(TradeORM.ticker == ticker.upper())
        if side:
            query = query.where(TradeORM.side == side.upper())

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        trades = result.scalars().all()

    return [
        {
            "id": t.id,
            "ticker": t.ticker,
            "side": t.side,
            "order_type": t.order_type,
            "quantity": t.quantity,
            "price": t.price,
            "total_value": t.total_value,
            "status": t.status,
            "broker_order_id": t.broker_order_id,
            "report_id": t.report_id,
            "is_closing_trade": t.is_closing_trade,
            "realised_pnl": t.realised_pnl,
            "realised_pnl_pct": t.realised_pnl_pct,
            "notes": t.notes,
            "executed_at": str(t.executed_at),
        }
        for t in trades
    ]
