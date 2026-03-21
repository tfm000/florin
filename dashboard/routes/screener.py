"""
Multi-factor stock screener — general-purpose equity screening.

Separate from the penny stock universe scanner. Uses yfinance's
EquityQuery + screen() API for server-side filtering.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["screener"])


class ScreenerResult(BaseModel):
    ticker: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    price: float | None = None
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    avg_volume: int | None = None
    change_pct: float | None = None


class ScreenerResponse(BaseModel):
    total: int
    results: list[ScreenerResult]


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
    sort_by: str = Query(default="intradaymarketcap", description="Sort field"),
    sort_asc: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=250),
    yf=Depends(get_yfinance_dep),
):
    """General-purpose multi-factor stock screener."""
    import asyncio

    def _screen() -> dict:
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
                # EquityQuery("and", ...) requires at least 2 operands
                operands.append(EquityQuery("gt", ["intradayprice", 0]))
            query = EquityQuery("and", operands)
            resp = screen(query, size=limit, offset=0,
                          sortField=sort_by, sortAsc=sort_asc)

            total = resp.get("total", 0) if resp else 0
            quotes = resp.get("quotes", []) if resp else []

            results = []
            for q in quotes:
                results.append(ScreenerResult(
                    ticker=q.get("symbol", ""),
                    name=q.get("shortName") or q.get("longName", ""),
                    exchange=q.get("exchange", ""),
                    sector=q.get("sector", ""),
                    industry=q.get("industry", ""),
                    market_cap=q.get("marketCap"),
                    price=q.get("regularMarketPrice"),
                    pe_ratio=q.get("trailingPE"),
                    dividend_yield=q.get("dividendYield"),
                    avg_volume=q.get("averageDailyVolume3Month"),
                    change_pct=q.get("regularMarketChangePercent"),
                ))

            return {"total": total, "results": results}

        except Exception:
            logger.exception("Screener query failed")
            return {"total": 0, "results": []}

    return await asyncio.to_thread(_screen)
