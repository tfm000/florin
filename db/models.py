"""
SQLAlchemy ORM models for persistent storage.

These map to database tables. They are distinct from the Pydantic models
in core/models.py — those are for in-flight data, these are for storage.
Conversion helpers are provided on each model.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def generate_id() -> str:
    """Generate a 16-character hex ID for use as a primary key."""
    return uuid4().hex[:16]


# =============================================================================
# Trades
# =============================================================================


class TradeORM(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    order_type: Mapped[str] = mapped_column(String(12), default="MARKET")
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    total_value: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="FILLED")
    broker_order_id: Mapped[str] = mapped_column(String(50), default="")
    report_id: Mapped[str] = mapped_column(String(16), default="", index=True)
    is_closing_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    realised_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realised_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


# =============================================================================
# Reports
# =============================================================================


class ReportORM(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    mode: Mapped[str] = mapped_column(String(12))  # single | consensus

    # Alert context
    alert_price: Mapped[float] = mapped_column(Float)
    alert_change_pct: Mapped[float] = mapped_column(Float)
    alert_volume: Mapped[int] = mapped_column(Integer, default=0)

    # Final recommendation
    final_recommendation: Mapped[str] = mapped_column(String(20))
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_confidence: Mapped[float] = mapped_column(Float, default=0.5)

    # Sentiment summary
    reddit_mentions: Mapped[int] = mapped_column(Integer, default=0)
    apewisdom_mentions: Mapped[int] = mapped_column(Integer, default=0)
    alphavantage_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    insider_buys: Mapped[int] = mapped_column(Integer, default=0)
    insider_sells: Mapped[int] = mapped_column(Integer, default=0)
    news_count: Mapped[int] = mapped_column(Integer, default=0)

    # Full report data (JSON blob)
    report_json: Mapped[str] = mapped_column(Text, default="{}")

    # User action
    user_action: Mapped[str] = mapped_column(String(10), default="PENDING")  # BUY | DENY | PENDING
    trade_id: Mapped[str | None] = mapped_column(
        String(16),
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
    )

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


# =============================================================================
# Alerts
# =============================================================================


class AlertORM(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="MOMENTUM")
    report_id: Mapped[str | None] = mapped_column(
        String(16),
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


# =============================================================================
# Universe cache
# =============================================================================


class UniverseStockORM(Base):
    __tablename__ = "universe"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str] = mapped_column(String(20), default="")
    t212_ticker: Mapped[str] = mapped_column(String(30), default="")
    sector: Mapped[str] = mapped_column(String(100), default="")
    industry: Mapped[str] = mapped_column(String(100), default="")
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inferred_market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_volume: Mapped[int] = mapped_column(Integer, default=0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    in_universe: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Settings (runtime-configurable via dashboard)
# =============================================================================


class SettingORM(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Telegram message tracking (for editing messages with position updates)
# =============================================================================


class TelegramMessageORM(Base):
    __tablename__ = "telegram_messages"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    chat_id: Mapped[str] = mapped_column(String(30))
    message_id: Mapped[int] = mapped_column(Integer)
    message_type: Mapped[str] = mapped_column(String(20))  # alert | position | status
    ticker: Mapped[str] = mapped_column(String(20), default="", index=True)
    report_id: Mapped[str | None] = mapped_column(
        String(16),
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Watchlist
# =============================================================================


class WatchlistORM(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    asset_type: Mapped[str] = mapped_column(
        String(20), default="equity"
    )  # equity, crypto, etf, bond, index
    notes: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Monitored Assets (live price tracking via Alpaca)
# =============================================================================


class MonitoredAssetORM(Base):
    __tablename__ = "monitored_assets"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")  # alpaca, manual
    asset_type: Mapped[str] = mapped_column(String(20), default="equity")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Model Portfolios
# =============================================================================


class PortfolioORM(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    group: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PortfolioHoldingORM(Base):
    __tablename__ = "portfolio_holdings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    portfolio_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(20))
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100


# =============================================================================
# Market Breadth Snapshots
# =============================================================================


class BreadthSnapshotORM(Base):
    __tablename__ = "breadth_snapshots"
    __table_args__ = (UniqueConstraint("date", "hour", name="uq_breadth_date_hour"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    hour: Mapped[int] = mapped_column(Integer, default=0)  # 0-23
    advancing: Mapped[int] = mapped_column(Integer, default=0)
    declining: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    ad_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Price Alerts
# =============================================================================


class PriceAlertORM(Base):
    __tablename__ = "price_alerts"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "above" or "below"
    target_price: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# =============================================================================
# News Sources
# =============================================================================


class NewsSourceORM(Base):
    __tablename__ = "news_sources"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    homepage: Mapped[str] = mapped_column(String(500))
    feeds: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of RSS URLs
    group: Mapped[str] = mapped_column(String(50), default="")  # e.g. "Finance", "Tech"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# News Stories
# =============================================================================


class NewsStoryORM(Base):
    __tablename__ = "news_stories"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    headline: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    url: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)


# =============================================================================
# Risk-Free Rates (G10 central bank overnight benchmarks)
# =============================================================================


class RiskFreeRateORM(Base):
    __tablename__ = "risk_free_rates"
    __table_args__ = (UniqueConstraint("currency", "date", name="uq_rfr_currency_date"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    currency: Mapped[str] = mapped_column(String(3), index=True)  # USD, GBP, etc.
    benchmark: Mapped[str] = mapped_column(String(20))  # SOFR, SONIA, etc.
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    rate: Mapped[float] = mapped_column(Float)  # Annual % (e.g. 4.5)
    source: Mapped[str] = mapped_column(String(100))  # API source name
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# CUSIP → Ticker Mapping Cache
# =============================================================================


class CusipTickerORM(Base):
    __tablename__ = "cusip_ticker_map"

    cusip: Mapped[str] = mapped_column(String(12), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Portfolio Summary Cache
# =============================================================================


class PortfolioCacheMetaORM(Base):
    """One row per portfolio: cached analytics + aggregated fundamentals."""

    __tablename__ = "portfolio_cache_meta"

    portfolio_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    start_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    end_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD

    # Full-range analytics
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    annualized_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    var_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvar_95: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Weighted fundamentals
    weighted_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_beta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Average fundamentals
    avg_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_beta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Max fundamentals
    max_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_beta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Min fundamentals
    min_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_beta: Mapped[float | None] = mapped_column(Float, nullable=True)

    holdings_count: Mapped[int] = mapped_column(Integer, default=0)
    priceable_count: Mapped[int] = mapped_column(Integer, default=0)

    computed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PortfolioCacheReturnORM(Base):
    """Daily portfolio return time series (prorated and non-prorated variants)."""

    __tablename__ = "portfolio_cache_returns"
    __table_args__ = (Index("ix_cache_returns_lookup", "portfolio_id", "prorated", "date"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    portfolio_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    cumulative_return: Mapped[float] = mapped_column(Float)
    prorated: Mapped[bool] = mapped_column(Boolean, default=False)


# =============================================================================
# Saved Screeners (user-configured filter presets)
# =============================================================================


class SavedScreenerORM(Base):
    """Saved screener filter configuration."""

    __tablename__ = "saved_screeners"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    filters_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON blob of all filter params
    sort_by: Mapped[str] = mapped_column(String(50), default="intradaymarketcap")
    sort_asc: Mapped[bool] = mapped_column(Boolean, default=False)

    # Phase 7: live alert fields (pre-created for migration efficiency)
    is_alert_active: Mapped[bool] = mapped_column(Boolean, default=False)
    max_alerts_per_day: Mapped[int] = mapped_column(Integer, default=10)
    alerts_sent_today: Mapped[int] = mapped_column(Integer, default=0)
    include_llm_report: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_types: Mapped[str] = mapped_column(
        Text,
        default='["announcement", "sentiment"]',
    )  # JSON list: subset of ["announcement", "sentiment"]
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Screener Alert Log (tracks which tickers were alerted per screener)
# =============================================================================


class ScreenerAlertLogORM(Base):
    """Log of screener alert notifications sent to the user."""

    __tablename__ = "screener_alert_log"
    __table_args__ = (Index("ix_screener_alert_screener_date", "screener_id", "sent_at"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    screener_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("saved_screeners.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_data_json: Mapped[str] = mapped_column(Text, default="{}")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Central Bank Policy Rates
# =============================================================================


class LLMModelORM(Base):
    """Registered LLM model for analysis.

    Each row represents a configured LLM provider + model combination
    with its API credentials. Users can register multiple models and
    assign them to different analysis roles (announcement, sentiment,
    consensus leader).
    """

    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    host: Mapped[str] = mapped_column(
        String(20), index=True
    )  # openrouter, gemini, groq, anthropic-cli
    model: Mapped[str] = mapped_column(
        String(100)
    )  # e.g. "claude-sonnet-4-20250514", "gemini-2.5-flash-lite"
    api_key: Mapped[str] = mapped_column(Text, default="")  # Optional for CLI-auth providers
    display_name: Mapped[str] = mapped_column(
        String(200)
    )  # e.g. "Anthropic CLI / claude-sonnet-4-20250514"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    thinking_mode: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default=None,
    )  # off, low, medium, high, max — only used by anthropic-cli
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PolicyRateORM(Base):
    """G10 central bank policy rates fetched from BIS CBPOL API."""

    __tablename__ = "policy_rates"
    __table_args__ = (UniqueConstraint("country_code", name="uq_policy_rate_country"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    country_code: Mapped[str] = mapped_column(String(3), index=True)  # US, XM, GB, ...
    country: Mapped[str] = mapped_column(String(50))
    central_bank: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Float)
    effective_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Economic Calendar Events
# =============================================================================


class EconomicEventORM(Base):
    """Economic calendar events — CB meetings, macro indicators, etc.

    Populated by the EconomicCalendarService from multiple sources:
    - Central bank meeting dates parsed from official websites
    - Rate values from BIS CBPOL, ECB, and BOC APIs
    - US macro indicator values from Alpha Vantage
    - Past FOMC decisions from the Fed RSS feed
    """

    __tablename__ = "economic_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_economic_event_key"),
        Index("ix_economic_events_date", "date"),
        Index("ix_economic_events_country", "country"),
        Index("ix_economic_events_category", "category"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    event_key: Mapped[str] = mapped_column(String(100))  # e.g. "fomc_2026-04-29", "us_cpi_2026-03"
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    event: Mapped[str] = mapped_column(String(100))  # Event name
    country: Mapped[str] = mapped_column(String(3))  # ISO code: US, EU, GB, JP, CA, etc.
    country_name: Mapped[str] = mapped_column(String(50), default="")
    institution: Mapped[str] = mapped_column(
        String(80), default=""
    )  # Federal Reserve, BLS, ECB, etc.
    category: Mapped[str] = mapped_column(
        String(30), default=""
    )  # Monetary Policy, Employment, etc.
    importance: Mapped[str] = mapped_column(String(10), default="high")  # high, medium, low
    expected: Mapped[str] = mapped_column(String(30), default="")  # Forecast value
    actual: Mapped[str] = mapped_column(String(30), default="")  # Actual released value
    previous: Mapped[str] = mapped_column(String(30), default="")  # Prior period value
    unit: Mapped[str] = mapped_column(String(30), default="")  # %, K persons, index, etc.
    description: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[str] = mapped_column(String(20), default="")  # Monthly, Quarterly, 8x/year
    source: Mapped[str] = mapped_column(
        String(30), default=""
    )  # fed_rss, ecb_api, bis, alpha_vantage, etc.
    indicator_key: Mapped[str] = mapped_column(String(30), default="")  # For history endpoint
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
