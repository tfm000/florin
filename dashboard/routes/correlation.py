"""
Correlation matrix API using copulax.

Computes pairwise correlations from daily returns using
any of copulax's 12 correlation methods.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["correlation"])

COPULAX_METHODS = [
    "pearson",
    "spearman",
    "kendall",
    "pp_kendall",
    "rm_pearson",
    "rm_spearman",
    "rm_kendall",
    "rm_pp_kendall",
    "laloux_pearson",
    "laloux_spearman",
    "laloux_kendall",
    "laloux_pp_kendall",
]


class CorrelationResponse(BaseModel):
    tickers: list[str]
    method: str
    matrix: list[list[float]]


@router.get("/correlation", response_model=CorrelationResponse)
async def get_correlation_matrix(
    tickers: str = Query(..., description="Comma-separated tickers"),
    method: str = Query(default="pearson", description="Correlation method"),
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    yf=Depends(get_yfinance_dep),
):
    """Compute pairwise correlation matrix using copulax."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        return CorrelationResponse(tickers=ticker_list, method=method, matrix=[[1.0]])

    if method not in COPULAX_METHODS:
        method = "pearson"

    # Fetch histories concurrently
    async def _fetch(sym):
        if start and end:
            return await yf.get_history(sym, start=start, end=end)
        return await yf.get_history(sym, period=period)

    histories = await asyncio.gather(*[_fetch(t) for t in ticker_list])

    def _compute():
        import numpy as np

        try:
            from copulax.multivariate import corr
        except ImportError:
            logger.error("copulax not installed")
            return [
                [1.0 if i == j else 0.0 for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]

        # Build aligned returns matrix
        # Normalise dates to YYYY-MM-DD (strip timezone info) so that
        # tickers from different exchanges with different tz offsets align.
        def _date_key(raw_date) -> str:
            s = str(raw_date)
            return s[:10]  # "2025-03-21" from "2025-03-21 00:00:00-04:00"

        # Find common dates
        date_sets = []
        for hist in histories:
            if hist:
                date_sets.append({_date_key(h["date"]) for h in hist})
            else:
                date_sets.append(set())

        if not date_sets:
            return [
                [1.0 if i == j else 0.0 for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]

        common_dates = sorted(set.intersection(*date_sets)) if all(date_sets) else []
        if len(common_dates) < 10:
            return [
                [1.0 if i == j else 0.0 for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]

        # Build price lookup per ticker (keyed by normalised date)
        returns_matrix = []
        for hist in histories:
            price_map = {_date_key(h["date"]): h["close"] for h in hist}
            prices = [price_map[d] for d in common_dates if d in price_map]
            # Compute simple returns
            rets = [
                (prices[i] / prices[i - 1]) - 1 for i in range(1, len(prices)) if prices[i - 1] > 0
            ]
            returns_matrix.append(rets)

        # Align lengths
        min_len = min(len(r) for r in returns_matrix)
        if min_len < 5:
            return [
                [1.0 if i == j else 0.0 for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]

        x = np.array([r[:min_len] for r in returns_matrix]).T  # (T, N)

        try:
            corr_matrix = corr(x, method=method)
            return [
                [round(float(corr_matrix[i, j]), 4) for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]
        except Exception:
            logger.exception("copulax corr() failed with method=%s", method)
            # Fallback to numpy
            corr_matrix = np.corrcoef(x.T)
            return [
                [round(float(corr_matrix[i, j]), 4) for j in range(len(ticker_list))]
                for i in range(len(ticker_list))
            ]

    matrix = await asyncio.to_thread(_compute)
    return CorrelationResponse(tickers=ticker_list, method=method, matrix=matrix)
