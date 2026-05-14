"""Short interest data from yfinance."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["short_interest"])


class ShortInterestResponse(BaseModel):
    ticker: str
    short_percent_of_float: float | None = None
    shares_short: int | None = None
    short_ratio: float | None = None  # days to cover
    shares_outstanding: int | None = None


@router.get("/short-interest/{ticker}", response_model=ShortInterestResponse)
async def get_short_interest(ticker: str, yf=Depends(get_yfinance_dep)):
    """Get short interest data for a ticker."""
    ticker = ticker.upper()
    info = await yf.get_info(ticker)
    return ShortInterestResponse(
        ticker=ticker,
        short_percent_of_float=info.get("short_interest"),
        shares_short=info.get("shares_short"),
        short_ratio=info.get("short_ratio"),
        shares_outstanding=info.get("shares_outstanding"),
    )
