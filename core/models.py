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


class AlphaVantageNewsSentiment(BaseModel):
    """Alpha Vantage news article with AI-scored sentiment.

    Each article includes overall sentiment and per-ticker relevance
    and sentiment scores. Powered by Alpha Vantage's NEWS_SENTIMENT
    endpoint with AI-driven scoring.

    Reference: https://www.alphavantage.co/documentation/#news-sentiment
    """
    title: str
    source: str = ""
    url: str = ""
    summary: str = ""
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    overall_sentiment_score: float = 0.0  # -1 to 1
    overall_sentiment_label: str = ""  # "Bullish", "Bearish", "Neutral", etc.
    ticker_relevance: float = 0.0  # 0–1
    ticker_sentiment_score: float = 0.0  # -1 to 1
    ticker_sentiment_label: str = ""


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


class WebSearchResult(BaseModel):
    """Single web search result from DuckDuckGo news search.

    Used to supplement news/sentiment data with web search results.
    Each result represents a news article found via DuckDuckGo's
    news search for a given stock ticker.
    """
    title: str
    snippet: str = ""
    url: str = ""
    source: str = ""  # Publisher / domain name
    date: str = ""  # ISO date string from DuckDuckGo


class Form8KFiling(BaseModel):
    """SEC Form 8-K filing with extracted text content.

    Material event disclosures required by the SEC when significant
    corporate events occur (earnings, acquisitions, leadership changes, etc.).
    The text_content field holds the extracted plain text, truncated to a
    reasonable length for LLM consumption.
    """
    ticker: str
    filed_date: datetime
    form_type: str = "8-K"
    description: str = ""
    items: list[str] = Field(default_factory=list)  # 8-K item numbers
    text_content: str = ""  # Extracted plain text (truncated)
    url: str = ""
    accession_number: str = ""


class SentimentData(BaseModel):
    """Aggregated sentiment from all sources for a single ticker."""
    ticker: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Reddit
    reddit_posts: list[RedditPost] = Field(default_factory=list)
    reddit_mention_count: int = 0

    # ApeWisdom (Reddit aggregation)
    apewisdom_rank: int = 0  # 0 = not trending
    apewisdom_mentions: int = 0
    apewisdom_upvotes: int = 0

    # Alpha Vantage News Sentiment
    alphavantage_articles: list[AlphaVantageNewsSentiment] = Field(default_factory=list)
    alphavantage_avg_sentiment: float = 0.0

    # SEC
    sec_filings: list[SECFiling] = Field(default_factory=list)
    insider_buy_count: int = 0
    insider_sell_count: int = 0

    # News
    news_articles: list[NewsArticle] = Field(default_factory=list)

    # Web Search (DuckDuckGo)
    web_search_results: list[WebSearchResult] = Field(default_factory=list)

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

        if self.apewisdom_rank > 0:
            lines.append(f"ApeWisdom: rank #{self.apewisdom_rank}, "
                          f"{self.apewisdom_mentions} mentions, "
                          f"{self.apewisdom_upvotes} upvotes")
        else:
            lines.append("ApeWisdom: not trending")

        if self.alphavantage_articles:
            lines.append(f"Alpha Vantage: {len(self.alphavantage_articles)} articles, "
                          f"avg sentiment {self.alphavantage_avg_sentiment:+.2f}")
            for a in self.alphavantage_articles[:3]:
                label = f" [{a.ticker_sentiment_label}]" if a.ticker_sentiment_label else ""
                lines.append(f"  - [{a.source}]{label} {a.title[:100]}")

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

        # Web Search results
        if self.web_search_results:
            lines.append(f"Web Search: {len(self.web_search_results)} results")
            for g in self.web_search_results[:5]:
                lines.append(f"  - [{g.source}] {g.title[:100]}")
                if g.snippet:
                    lines.append(f"    {g.snippet[:150]}")

        return "\n".join(lines)


# =============================================================================
# LLM Analysis Models
# =============================================================================


class AnalysisType(str, Enum):
    """Type of LLM analysis task."""
    ANNOUNCEMENT = "announcement"
    SENTIMENT = "sentiment"


class AnalysisResult(BaseModel):
    """Output from a single LLM analysis — either announcement or sentiment.

    Score semantics: 0 = extremely negative, 5 = neutral, 10 = extremely positive.
    Used for both individual analyst results and consensus leader output.
    """
    provider: str  # "groq", "gemini", "claude-cli", "openrouter"
    model: str = ""
    analysis_type: AnalysisType = AnalysisType.SENTIMENT
    score: float = Field(default=5.0, ge=0.0, le=10.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    bullish_signals: list[str] = Field(default_factory=list)
    bearish_signals: list[str] = Field(default_factory=list)
    recommendation: Recommendation = Recommendation.HOLD
    raw_response: str = ""  # Full LLM response for debugging
    latency_ms: int = 0
    error: Optional[str] = None


class AnalysisReport(BaseModel):
    """Complete analysis report for a stock alert.

    Supports single-model and consensus modes, with separate results
    for announcement analysis (Form 8-K) and sentiment analysis
    (web search, Reddit, ApeWisdom, Alpha Vantage).
    """
    id: str = ""
    ticker: str
    alert: AlertSignal
    sentiment: SentimentData
    filings: list[Form8KFiling] = Field(default_factory=list)

    # Single-mode results (one model per analysis type)
    announcement_analysis: Optional[AnalysisResult] = None
    sentiment_analysis: Optional[AnalysisResult] = None

    # Consensus-mode results (all models + leader synthesis)
    announcement_analyses: list[AnalysisResult] = Field(default_factory=list)
    sentiment_analyses: list[AnalysisResult] = Field(default_factory=list)
    announcement_consensus: Optional[AnalysisResult] = None
    sentiment_consensus: Optional[AnalysisResult] = None

    # Final scores (from single result or consensus leader)
    announcement_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    final_recommendation: Recommendation = Recommendation.HOLD
    final_confidence: float = 0.0

    mode: str = "single"  # "single" | "consensus"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_best_announcement(self) -> Optional[AnalysisResult]:
        """Return the best announcement analysis (consensus or single)."""
        if self.mode == "consensus" and self.announcement_consensus:
            return self.announcement_consensus
        return self.announcement_analysis

    def get_best_sentiment(self) -> Optional[AnalysisResult]:
        """Return the best sentiment analysis (consensus or single)."""
        if self.mode == "consensus" and self.sentiment_consensus:
            return self.sentiment_consensus
        return self.sentiment_analysis


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
