"""
SQLAlchemy ORM models for persistent storage.

These map to database tables. They are distinct from the Pydantic models
in core/models.py — those are for in-flight data, these are for storage.
Conversion helpers are provided on each model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
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
    realised_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realised_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )


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

    # Fraud risk
    fraud_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    fraud_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    fraud_flags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list

    # Sentiment summary
    reddit_mentions: Mapped[int] = mapped_column(Integer, default=0)
    stocktwits_bullish: Mapped[int] = mapped_column(Integer, default=0)
    stocktwits_bearish: Mapped[int] = mapped_column(Integer, default=0)
    insider_buys: Mapped[int] = mapped_column(Integer, default=0)
    insider_sells: Mapped[int] = mapped_column(Integer, default=0)
    news_count: Mapped[int] = mapped_column(Integer, default=0)

    # Full report data (JSON blob)
    report_json: Mapped[str] = mapped_column(Text, default="{}")

    # User action
    user_action: Mapped[str] = mapped_column(String(10), default="PENDING")  # BUY | DENY | PENDING
    trade_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )


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
    report_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )


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
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inferred_market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
    report_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
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
    asset_type: Mapped[str] = mapped_column(String(20), default="equity")  # equity, crypto, etf, bond, index
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
    group: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PortfolioHoldingORM(Base):
    __tablename__ = "portfolio_holdings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    portfolio_id: Mapped[str] = mapped_column(String(16), index=True)
    ticker: Mapped[str] = mapped_column(String(20))
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100


# =============================================================================
# Market Breadth Snapshots
# =============================================================================

class BreadthSnapshotORM(Base):
    __tablename__ = "breadth_snapshots"

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
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    url: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# Risk-Free Rates (G10 central bank overnight benchmarks)
# =============================================================================

class RiskFreeRateORM(Base):
    __tablename__ = "risk_free_rates"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=generate_id)
    currency: Mapped[str] = mapped_column(String(3), index=True)      # USD, GBP, etc.
    benchmark: Mapped[str] = mapped_column(String(20))                 # SOFR, SONIA, etc.
    date: Mapped[str] = mapped_column(String(10), index=True)          # YYYY-MM-DD
    rate: Mapped[float] = mapped_column(Float)                         # Annual % (e.g. 4.5)
    source: Mapped[str] = mapped_column(String(100))                   # API source name
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# =============================================================================
# CUSIP → Ticker Mapping Cache
# =============================================================================

class CusipTickerORM(Base):
    __tablename__ = "cusip_ticker_map"

    cusip: Mapped[str] = mapped_column(String(12), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
