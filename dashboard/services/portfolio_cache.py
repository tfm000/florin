"""
Portfolio summary cache — read/write/invalidate cached portfolio results.

Stores portfolio-level returns (prorated + non-prorated), analytics, and
aggregated fundamentals in SQLite so repeat page loads are instant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import delete, select

from data.yfinance_provider import _period_cutoff
from db.models import (
    PortfolioCacheMetaORM,
    PortfolioCacheReturnORM,
    generate_id,
)

logger = logging.getLogger(__name__)


class PortfolioCacheService:
    """Read and write portfolio-level cached results from SQLite."""

    def __init__(self, db):
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_cached_summary(
        self,
        portfolio_id: str,
        period: str,
        prorated: bool,
        start: str = "",
        end: str = "",
    ) -> dict | None:
        """Load cached summary, slicing returns to requested period.

        Returns a dict matching PortfolioSummary fields, or None if no
        cache exists at all. Always serves whatever cached data is
        available — the SSE endpoint will push fresh data afterwards.
        """
        async with self._db.session() as session:
            meta = await session.get(PortfolioCacheMetaORM, portfolio_id)
            if meta is None:
                return None

            # Slice cached returns to the requested window (best-effort)
            if start:
                req_start = start
                req_end = end or "9999-12-31"
            else:
                req_start = _period_cutoff(period) or meta.start_date
                req_end = "9999-12-31"

            # Fetch return points within the requested range
            stmt = (
                select(PortfolioCacheReturnORM)
                .where(
                    PortfolioCacheReturnORM.portfolio_id == portfolio_id,
                    PortfolioCacheReturnORM.prorated == prorated,
                    PortfolioCacheReturnORM.date >= req_start,
                    PortfolioCacheReturnORM.date <= req_end,
                )
                .order_by(PortfolioCacheReturnORM.date)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                return None

            return_points = [
                {"date": r.date, "portfolio": r.cumulative_return}
                for r in rows
            ]

            # Recompute analytics for the sliced period
            analytics = self._recompute_analytics(return_points, portfolio_id, period)

            return {
                "portfolio_id": portfolio_id,
                "period": period,
                "analytics": analytics,
                "returns": return_points,
                "holdings": [],  # Not cached — populated by fresh computation
                # Fundamentals from meta (not period-dependent)
                "weighted_pe": meta.weighted_pe,
                "weighted_forward_pe": meta.weighted_forward_pe,
                "weighted_dividend_yield": meta.weighted_dividend_yield,
                "weighted_beta": meta.weighted_beta,
                "avg_pe": meta.avg_pe,
                "avg_forward_pe": meta.avg_forward_pe,
                "avg_dividend_yield": meta.avg_dividend_yield,
                "avg_beta": meta.avg_beta,
                "max_pe": meta.max_pe,
                "max_forward_pe": meta.max_forward_pe,
                "max_dividend_yield": meta.max_dividend_yield,
                "max_beta": meta.max_beta,
                "min_pe": meta.min_pe,
                "min_forward_pe": meta.min_forward_pe,
                "min_dividend_yield": meta.min_dividend_yield,
                "min_beta": meta.min_beta,
                "holdings_count": meta.holdings_count,
                "priceable_count": meta.priceable_count,
                "cached": True,
                "cached_at": meta.computed_at.isoformat() if meta.computed_at else None,
            }

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_summary(
        self,
        portfolio_id: str,
        summary: dict,
        returns_prorated: list[dict],
        returns_non_prorated: list[dict],
    ) -> None:
        """Persist computed summary to cache tables.

        Stores BOTH prorated and non-prorated return series.
        Replaces any existing cache for this portfolio.
        """
        all_dates = set()
        for r in returns_prorated:
            all_dates.add(r["date"])
        for r in returns_non_prorated:
            all_dates.add(r["date"])

        if not all_dates:
            return

        start_date = min(all_dates)
        end_date = max(all_dates)

        async with self._db.session() as session:
            # Delete existing cache
            await session.execute(
                delete(PortfolioCacheReturnORM)
                .where(PortfolioCacheReturnORM.portfolio_id == portfolio_id)
            )
            await session.execute(
                delete(PortfolioCacheMetaORM)
                .where(PortfolioCacheMetaORM.portfolio_id == portfolio_id)
            )

            # Insert meta row
            meta = PortfolioCacheMetaORM(
                portfolio_id=portfolio_id,
                start_date=start_date,
                end_date=end_date,
                total_return=summary.get("analytics", {}).get("total_return") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "total_return", None),
                annualized_vol=summary.get("analytics", {}).get("annualized_vol") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "annualized_vol", None),
                sharpe=summary.get("analytics", {}).get("sharpe") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "sharpe", None),
                sortino=summary.get("analytics", {}).get("sortino") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "sortino", None),
                max_drawdown=summary.get("analytics", {}).get("max_drawdown") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "max_drawdown", None),
                var_95=summary.get("analytics", {}).get("var_95") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "var_95", None),
                cvar_95=summary.get("analytics", {}).get("cvar_95") if isinstance(summary.get("analytics"), dict) else getattr(summary.get("analytics"), "cvar_95", None),
                weighted_pe=summary.get("weighted_pe"),
                weighted_forward_pe=summary.get("weighted_forward_pe"),
                weighted_dividend_yield=summary.get("weighted_dividend_yield"),
                weighted_beta=summary.get("weighted_beta"),
                avg_pe=summary.get("avg_pe"),
                avg_forward_pe=summary.get("avg_forward_pe"),
                avg_dividend_yield=summary.get("avg_dividend_yield"),
                avg_beta=summary.get("avg_beta"),
                max_pe=summary.get("max_pe"),
                max_forward_pe=summary.get("max_forward_pe"),
                max_dividend_yield=summary.get("max_dividend_yield"),
                max_beta=summary.get("max_beta"),
                min_pe=summary.get("min_pe"),
                min_forward_pe=summary.get("min_forward_pe"),
                min_dividend_yield=summary.get("min_dividend_yield"),
                min_beta=summary.get("min_beta"),
                holdings_count=summary.get("holdings_count", 0),
                priceable_count=summary.get("priceable_count", 0),
                computed_at=datetime.now(timezone.utc),
            )
            session.add(meta)

            # Bulk insert return rows
            for r in returns_non_prorated:
                session.add(PortfolioCacheReturnORM(
                    id=generate_id(),
                    portfolio_id=portfolio_id,
                    date=r["date"],
                    cumulative_return=r["portfolio"],
                    prorated=False,
                ))
            for r in returns_prorated:
                session.add(PortfolioCacheReturnORM(
                    id=generate_id(),
                    portfolio_id=portfolio_id,
                    date=r["date"],
                    cumulative_return=r["portfolio"],
                    prorated=True,
                ))

            await session.commit()

        logger.info(
            "Saved portfolio cache for %s: %s to %s (%d non-prorated, %d prorated returns)",
            portfolio_id, start_date, end_date,
            len(returns_non_prorated), len(returns_prorated),
        )

    # ------------------------------------------------------------------
    # Invalidate
    # ------------------------------------------------------------------

    async def invalidate(self, portfolio_id: str) -> None:
        """Delete all cache entries for a portfolio."""
        async with self._db.session() as session:
            await session.execute(
                delete(PortfolioCacheReturnORM)
                .where(PortfolioCacheReturnORM.portfolio_id == portfolio_id)
            )
            await session.execute(
                delete(PortfolioCacheMetaORM)
                .where(PortfolioCacheMetaORM.portfolio_id == portfolio_id)
            )
            await session.commit()
        logger.debug("Invalidated portfolio cache for %s", portfolio_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_analytics(
        return_points: list[dict],
        portfolio_id: str,
        period: str,
    ) -> dict:
        """Recompute analytics from a cached cumulative return series.

        Converts cumulative returns to a synthetic price series starting
        at 100, then uses compute_full_stats for sharpe/sortino/VaR etc.
        """
        if len(return_points) < 2:
            return {
                "portfolio_id": portfolio_id,
                "period": period,
            }

        # Convert cumulative_return (%) back to price series: price = 100 * (1 + cum/100)
        cum_returns = np.array([p["portfolio"] for p in return_points], dtype=np.float64)
        prices = 100.0 * (1.0 + cum_returns / 100.0)

        try:
            from stats.core import compute_full_stats
            stats = compute_full_stats(prices)
            total_ret = (prices[-1] / prices[0] - 1) * 100
            return {
                "portfolio_id": portfolio_id,
                "period": period,
                "total_return": round(total_ret, 2),
                "annualized_vol": round(stats.returns.annualized_volatility, 2),
                "sharpe": round(stats.risk_adjusted.sharpe, 4),
                "sortino": round(stats.risk_adjusted.sortino, 4),
                "max_drawdown": round(stats.drawdown.max_drawdown_pct, 2),
                "var_95": round(stats.var.var_95, 2),
                "cvar_95": round(stats.var.cvar_95, 2),
            }
        except Exception:
            logger.warning("Failed to recompute analytics from cache for %s", portfolio_id)
            return {
                "portfolio_id": portfolio_id,
                "period": period,
            }
