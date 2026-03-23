"""
Core data models (Pydantic) used across all modules.

These are pure data containers — no business logic, no I/O.
Every inter-module data exchange uses one of these models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class Exchange(str, Enum):
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    NYSE_ARCA = "NYSE ARCA"
    NYSE_MKT = "NYSE MKT"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Recommendation(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    AVOID = "AVOID"
    STRONG_AVOID = "STRONG_AVOID"


class FraudRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgreementLevel(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    DIVIDED = "DIVIDED"


class AlertSource(str, Enum):
    MOMENTUM = "MOMENTUM"
    MANUAL = "MANUAL"


# =============================================================================
# Market Data Models
# =============================================================================

class StockQuote(BaseModel):
    """Real-time or snapshot quote for a single stock."""
    ticker: str
    price: float
    open_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    volume: int = 0
    change_pct: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def change_from_open(self) -> float:
        if self.open_price == 0:
            return 0.0
        return ((self.price - self.open_price) / self.open_price) * 100

    @property
    def change_from_prev_close(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return ((self.price - self.prev_close) / self.prev_close) * 100


class StockInfo(BaseModel):
    """Static metadata about a stock in the universe."""
    ticker: str
    name: str = ""
    exchange: str = ""
    t212_ticker: str = ""  # Trading 212 internal ticker format
    sector: str = ""
    industry: str = ""
    market_cap: Optional[float] = None
    shares_outstanding: Optional[int] = None
    inferred_market_cap: Optional[float] = None  # shares_outstanding × price
    avg_volume: int = 0
    last_price: float = 0.0
    in_universe: bool = True  # Still qualifies for the universe


class BarData(BaseModel):
    """Single OHLCV bar (minute, hourly, daily)."""
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


# =============================================================================
# Alert Models
# =============================================================================

class AlertSignal(BaseModel):
    """Fired when scanner detects a qualifying move."""
    id: str = Field(default_factory=lambda: uuid4().hex[:16])
    ticker: str
    price: float
    change_pct: float
    volume: int
    avg_volume: int = 0
    source: AlertSource = AlertSource.MOMENTUM
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Sentiment Models
# =============================================================================

class RedditPost(BaseModel):
    """Single Reddit post or comment mentioning a ticker."""
    subreddit: str
    title: str
    body: str = ""
    score: int = 0
    num_comments: int = 0
    upvote_ratio: float = 0.0
    url: str = ""
    author: str = ""
    author_karma: int = 0
    account_age_days: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StockTwitsMessage(BaseModel):
    """Single StockTwits message."""
    text: str
    sentiment: Optional[str] = None  # "Bullish" | "Bearish" | None
    likes: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SECFiling(BaseModel):
    """Single SEC filing reference."""
    form_type: str
    filed_date: datetime
    description: str = ""
    url: str = ""
    # For Form 4 (insider trades)
    insider_name: str = ""
    insider_title: str = ""  # "CEO", "Director", "10% Owner", etc.
    transaction_type: str = ""  # "Purchase" | "Sale" | "Grant" | "Exercise"
    shares: float = 0.0
    price_per_share: float = 0.0
    post_transaction_shares: float = 0.0  # Holdings after transaction


class NewsArticle(BaseModel):
    """Single news article."""
    title: str
    source: str = ""
    url: str = ""
    summary: str = ""
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    relevance_score: float = 0.0


class SentimentData(BaseModel):
    """Aggregated sentiment from all sources for a single ticker."""
    ticker: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Reddit
    reddit_posts: list[RedditPost] = Field(default_factory=list)
    reddit_mention_count: int = 0

    # StockTwits
    stocktwits_messages: list[StockTwitsMessage] = Field(default_factory=list)
    stocktwits_bullish_count: int = 0
    stocktwits_bearish_count: int = 0

    # SEC
    sec_filings: list[SECFiling] = Field(default_factory=list)
    insider_buy_count: int = 0
    insider_sell_count: int = 0

    # News
    news_articles: list[NewsArticle] = Field(default_factory=list)

    # Metadata
    sources_queried: int = 0
    sources_succeeded: int = 0
    data_quality: str = "unknown"  # "high" | "medium" | "low" | "insufficient"

    def to_summary(self) -> str:
        """Human-readable summary for LLM prompts."""
        lines = []
        lines.append(f"Reddit: {self.reddit_mention_count} mentions across "
                      f"{len(self.reddit_posts)} posts")
        if self.reddit_posts:
            top = sorted(self.reddit_posts, key=lambda p: p.score, reverse=True)[:3]
            for p in top:
                lines.append(f"  - [{p.subreddit}] (score:{p.score}) {p.title[:100]}")

        lines.append(f"StockTwits: {self.stocktwits_bullish_count} bullish, "
                      f"{self.stocktwits_bearish_count} bearish "
                      f"({len(self.stocktwits_messages)} messages)")

        lines.append(f"SEC: {len(self.sec_filings)} recent filings, "
                      f"{self.insider_buy_count} insider buys, "
                      f"{self.insider_sell_count} insider sells")
        # Show insider transaction details (top 5 by shares)
        insider_filings = [f for f in self.sec_filings if f.insider_name and f.transaction_type]
        insider_filings.sort(key=lambda f: f.shares, reverse=True)
        for f in insider_filings[:5]:
            detail = f"  Insider: {f.insider_name}"
            if f.insider_title:
                detail += f" ({f.insider_title})"
            detail += f" — {f.transaction_type}"
            if f.shares > 0:
                detail += f" {f.shares:,.0f} shares"
                if f.price_per_share > 0:
                    detail += f" @ ${f.price_per_share:.2f}"
            lines.append(detail)
        # Show non-Form-4 filings
        other_filings = [f for f in self.sec_filings if f.form_type != "4"]
        for f in other_filings[:3]:
            lines.append(f"  [{f.form_type}] {f.filed_date.strftime('%Y-%m-%d')} — {f.description}")

        lines.append(f"News: {len(self.news_articles)} articles")
        if self.news_articles:
            for a in self.news_articles[:3]:
                lines.append(f"  - [{a.source}] {a.title[:100]}")

        return "\n".join(lines)


# =============================================================================
# Fraud / Risk Models
# =============================================================================

class FraudRiskScore(BaseModel):
    """Pump-and-dump / fraud risk assessment."""
    ticker: str
    score: float = Field(default=0.0, ge=0.0, le=10.0)  # 0 = safe, 10 = extreme risk
    risk_level: FraudRisk = FraudRisk.LOW
    flags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_summary(self) -> str:
        lines = [f"Fraud Risk: {self.risk_level.value} (score: {self.score:.1f}/10, "
                 f"confidence: {self.confidence:.0%})"]
        for flag in self.flags:
            lines.append(f"  ⚠ {flag}")
        if not self.flags:
            lines.append("  ✓ No fraud indicators detected")
        return "\n".join(lines)


# =============================================================================
# LLM Analysis Models
# =============================================================================

class LLMAnalysis(BaseModel):
    """Output from a single LLM analyser."""
    provider: str  # "ollama", "groq", "gemini", "claude", "finbert"
    model: str = ""
    sentiment_score: float = Field(default=0.0, ge=-10.0, le=10.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    bullish_signals: list[str] = Field(default_factory=list)
    bearish_signals: list[str] = Field(default_factory=list)
    risk_level: int = Field(default=3, ge=1, le=5)
    fraud_risk: FraudRisk = FraudRisk.LOW
    recommendation: Recommendation = Recommendation.HOLD
    summary: str = ""
    key_factors: list[str] = Field(default_factory=list)
    raw_response: str = ""  # Full LLM response for debugging
    latency_ms: int = 0
    error: Optional[str] = None


class AnalysisReport(BaseModel):
    """Complete analysis report for a stock alert — either single or consensus mode."""
    id: str = ""
    ticker: str
    alert: AlertSignal
    sentiment: SentimentData
    fraud_risk: FraudRiskScore

    # Single-mode fields
    primary_analysis: Optional[LLMAnalysis] = None

    # Consensus-mode fields
    individual_analyses: list[LLMAnalysis] = Field(default_factory=list)
    consensus: Optional[LLMAnalysis] = None  # Meta-analysis

    # Final recommendation (from primary or consensus)
    final_recommendation: Recommendation = Recommendation.HOLD
    final_score: float = 0.0
    final_confidence: float = 0.0

    mode: str = "single"  # "single" | "consensus"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_best_analysis(self) -> Optional[LLMAnalysis]:
        """Return the primary analysis (single mode) or consensus (consensus mode)."""
        if self.mode == "consensus" and self.consensus:
            return self.consensus
        return self.primary_analysis


class ConsensusAnalysis(BaseModel):
    """Meta-analysis output from consensus mode."""
    consensus_score: float = Field(default=0.0, ge=-10.0, le=10.0)
    agreement_level: AgreementLevel = AgreementLevel.MODERATE
    points_of_agreement: list[str] = Field(default_factory=list)
    points_of_disagreement: list[str] = Field(default_factory=list)
    strongest_bullish_argument: str = ""
    strongest_bearish_argument: str = ""
    consensus_recommendation: Recommendation = Recommendation.HOLD
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = ""
    dissenting_view: Optional[str] = None


# =============================================================================
# Trading / Broker Models
# =============================================================================

class Position(BaseModel):
    """An open position in the broker account."""
    ticker: str
    t212_ticker: str = ""
    quantity: float
    avg_price: float
    current_price: float = 0.0
    unrealised_pnl: float = 0.0
    unrealised_pnl_pct: float = 0.0
    market_value: float = 0.0
    opened_at: Optional[datetime] = None

    def update_pnl(self, current_price: float) -> None:
        self.current_price = current_price
        self.market_value = self.quantity * current_price
        cost_basis = self.quantity * self.avg_price
        self.unrealised_pnl = self.market_value - cost_basis
        if cost_basis > 0:
            self.unrealised_pnl_pct = (self.unrealised_pnl / cost_basis) * 100


class TradeRecord(BaseModel):
    """Record of an executed trade."""
    id: str = ""
    ticker: str
    side: Side
    order_type: OrderType = OrderType.MARKET
    quantity: float
    price: float
    total_value: float = 0.0
    status: OrderStatus = OrderStatus.FILLED
    broker_order_id: str = ""
    report_id: str = ""  # Link to the analysis report that triggered this trade
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: str = ""

    # For closed positions — P&L tracking
    is_closing_trade: bool = False
    realised_pnl: Optional[float] = None
    realised_pnl_pct: Optional[float] = None


class AccountSummary(BaseModel):
    """Broker account overview."""
    account_id: int = 0
    currency: str = "GBP"
    cash_available: float = 0.0
    cash_in_pies: float = 0.0
    reserved_for_orders: float = 0.0
    invested_value: float = 0.0
    total_value: float = 0.0
    unrealised_pnl: float = 0.0
    realised_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OrderRequest(BaseModel):
    """Request to place an order with the broker."""
    ticker: str
    side: Side
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    # For value-based orders (T212 supports fractional shares)
    target_value: Optional[float] = None
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None


class OrderResult(BaseModel):
    """Response from broker after placing an order."""
    success: bool
    order_id: str = ""
    ticker: str = ""
    side: Side = Side.BUY
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    error_message: str = ""
    raw_response: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Trading Statistics
# =============================================================================

class TradingStats(BaseModel):
    """Aggregated trading performance statistics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    avg_hold_time_hours: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: Optional[float] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
