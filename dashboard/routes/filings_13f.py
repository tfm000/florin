"""
13F filings API — search institutional filers, view holdings, download.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["13f"])


class FilerResult(BaseModel):
    cik: str
    name: str
    filing_date: str = ""


class FilingResult(BaseModel):
    accession: str
    date: str
    document: str = ""


class HoldingResult(BaseModel):
    cusip: str
    ticker: str = ""
    name: str = ""
    title: str = ""
    shares: int = 0
    value: float = 0
    weight: float = 0  # % of portfolio


@router.get("/13f/search", response_model=list[FilerResult])
async def search_13f_filers(
    q: str = Query(..., min_length=2, description="Fund/filer name"),
):
    """Search for institutional filers by name."""
    from data.sec_13f_provider import search_filers
    results = await search_filers(q)
    return [FilerResult(**r) for r in results]


@router.get("/13f/filings", response_model=list[FilingResult])
async def get_13f_filings(
    cik: str = Query(..., description="CIK number"),
):
    """Get list of 13F-HR filings for a filer."""
    from data.sec_13f_provider import get_filings
    filings = await get_filings(cik)
    return [FilingResult(**f) for f in filings if f.get("accession")]


@router.get("/13f/holdings", response_model=list[HoldingResult])
async def get_13f_holdings(
    cik: str = Query(...),
    accession: str = Query(...),
):
    """Get parsed holdings from a specific 13F filing with CUSIP→ticker mapping."""
    from data.sec_13f_provider import get_holdings, map_cusips_to_tickers

    holdings = await get_holdings(cik, accession)
    if not holdings:
        return []

    # Map CUSIPs to tickers
    cusips = [h.get("cusip", "") for h in holdings if h.get("cusip")]
    ticker_map = await map_cusips_to_tickers(cusips)

    # Calculate weights
    total_value = sum(h.get("value", 0) for h in holdings)

    results = []
    for h in holdings:
        cusip = h.get("cusip", "")
        value = h.get("value", 0)
        results.append(HoldingResult(
            cusip=cusip,
            ticker=ticker_map.get(cusip, ""),
            name=h.get("name", ""),
            title=h.get("title", ""),
            shares=h.get("shares", 0),
            value=value,
            weight=round(value / total_value * 100, 2) if total_value > 0 else 0,
        ))

    # Sort by value descending
    results.sort(key=lambda r: r.value, reverse=True)
    return results


@router.get("/13f/holdings/download")
async def download_13f_holdings(
    cik: str = Query(...),
    accession: str = Query(...),
):
    """Download holdings as CSV."""
    holdings = await get_13f_holdings(cik=cik, accession=accession)

    def generate():
        yield "cusip,ticker,name,title,shares,value,weight_pct\n"
        for h in holdings:
            yield f"{h.cusip},{h.ticker},{h.name},{h.title},{h.shares},{h.value},{h.weight}\n"

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=13f_{cik}_{accession}.csv"},
    )
