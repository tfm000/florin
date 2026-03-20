"""GET /api/reports — Generated analysis reports."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, desc

from dashboard.deps import get_db
from db.models import ReportORM

router = APIRouter(tags=["reports"])


@router.get("/reports")
async def get_reports(
    ticker: str | None = None,
    recommendation: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Get paginated list of analysis reports."""
    db = get_db()
    async with db.session() as session:
        query = select(ReportORM).order_by(desc(ReportORM.generated_at))

        if ticker:
            query = query.where(ReportORM.ticker == ticker.upper())
        if recommendation:
            query = query.where(ReportORM.final_recommendation == recommendation.upper())

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        reports = result.scalars().all()

    return [_report_summary(r) for r in reports]


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """Get full report detail by ID."""
    db = get_db()
    async with db.session() as session:
        result = await session.execute(
            select(ReportORM).where(ReportORM.id == report_id)
        )
        report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(404, f"Report {report_id} not found")

    data = _report_summary(report)
    # Include full report JSON
    try:
        data["report_data"] = json.loads(report.report_json)
    except (json.JSONDecodeError, TypeError):
        data["report_data"] = {}
    return data


def _report_summary(r: ReportORM) -> dict:
    return {
        "id": r.id,
        "ticker": r.ticker,
        "mode": r.mode,
        "alert_price": r.alert_price,
        "alert_change_pct": r.alert_change_pct,
        "alert_volume": r.alert_volume,
        "final_recommendation": r.final_recommendation,
        "final_score": r.final_score,
        "final_confidence": r.final_confidence,
        "fraud_risk_level": r.fraud_risk_level,
        "fraud_risk_score": r.fraud_risk_score,
        "fraud_flags": json.loads(r.fraud_flags) if r.fraud_flags else [],
        "reddit_mentions": r.reddit_mentions,
        "stocktwits_bullish": r.stocktwits_bullish,
        "stocktwits_bearish": r.stocktwits_bearish,
        "insider_buys": r.insider_buys,
        "insider_sells": r.insider_sells,
        "news_count": r.news_count,
        "user_action": r.user_action,
        "trade_id": r.trade_id,
        "generated_at": str(r.generated_at),
    }
