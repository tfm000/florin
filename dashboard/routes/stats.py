"""GET /api/stats — Trading statistics and performance metrics."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select, func

from dashboard.deps import get_db
from db.models import TradeORM

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def get_stats():
    """Get aggregated trading statistics."""
    db = get_db()
    async with db.session() as session:
        # Total trades
        total_result = await session.execute(select(func.count(TradeORM.id)))
        total_trades = total_result.scalar() or 0

        if total_trades == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0,
                "best_trade_pnl": 0.0,
                "worst_trade_pnl": 0.0,
            }

        # Closing trades with P&L
        closing_query = select(TradeORM).where(
            TradeORM.is_closing_trade.is_(True),
            TradeORM.realised_pnl.isnot(None),
        )
        result = await session.execute(closing_query)
        closing_trades = result.scalars().all()

        winning = [t for t in closing_trades if t.realised_pnl and t.realised_pnl > 0]
        losing = [t for t in closing_trades if t.realised_pnl and t.realised_pnl < 0]
        total_pnl = sum(t.realised_pnl for t in closing_trades if t.realised_pnl)

        win_count = len(winning)
        lose_count = len(losing)
        round_trips = win_count + lose_count
        win_rate = (win_count / round_trips * 100) if round_trips > 0 else 0.0

        pnl_values = [t.realised_pnl for t in closing_trades if t.realised_pnl is not None]

    return {
        "total_trades": total_trades,
        "round_trip_trades": round_trips,
        "winning_trades": win_count,
        "losing_trades": lose_count,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / round_trips, 2) if round_trips > 0 else 0.0,
        "best_trade_pnl": round(max(pnl_values), 2) if pnl_values else 0.0,
        "worst_trade_pnl": round(min(pnl_values), 2) if pnl_values else 0.0,
    }
