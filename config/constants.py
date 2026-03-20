"""
Application-wide constants and magic values.
"""

# --- Exchanges ---
SUPPORTED_EXCHANGES = {"NASDAQ", "NYSE", "NYSE ARCA", "NYSE MKT"}

# --- Trading 212 ticker suffix mapping ---
# T212 uses format like AAPL_US_EQ for US equities
T212_TICKER_SUFFIX = "_US_EQ"

# --- Reddit subreddits to monitor ---
PENNY_STOCK_SUBREDDITS = [
    "pennystocks",
    "wallstreetbets",
    "stocks",
    "investing",
    "smallstreetbets",
    "RobinHoodPennyStocks",
    "Shortsqueeze",
]

# --- StockTwits ---
STOCKTWITS_API_BASE = "https://api.stocktwits.com/api/2"

# --- SEC EDGAR ---
SEC_EDGAR_BASE = "https://efts.sec.gov/LATEST"
SEC_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_EDGAR_USER_AGENT = "SentinelTerminal admin@example.com"

# --- Filing types of interest ---
SEC_FORM_TYPES = {
    "4": "Insider Trading",
    "8-K": "Material Event",
    "13F-HR": "Institutional Holdings",
    "10-K": "Annual Report",
    "10-Q": "Quarterly Report",
    "SC 13D": "Beneficial Ownership (>5%)",
    "SC 13G": "Passive Beneficial Ownership (>5%)",
}

# --- Fraud detection thresholds ---
FRAUD_VOLUME_SPIKE_MULTIPLIER = 10.0  # Volume > 10x average = suspicious
FRAUD_REDDIT_MIN_ACCOUNT_AGE_DAYS = 30  # New accounts = suspicious
FRAUD_REDDIT_MIN_KARMA = 100
FRAUD_NO_FILING_DAYS = 90  # No SEC filings in 90 days = flag
FRAUD_COORDINATED_POST_WINDOW_MINUTES = 60
FRAUD_COORDINATED_POST_THRESHOLD = 5  # 5+ posts in window from new accounts

# --- LLM prompt templates ---
ANALYSIS_SYSTEM_PROMPT = """You are a senior financial analyst specialising in US penny stocks 
(stocks trading under $5 on NASDAQ/NYSE). You are cautious, data-driven, and particularly alert 
to pump-and-dump schemes and market manipulation.

Your task is to analyse a penny stock that has shown significant price momentum and provide a 
structured assessment based on the sentiment data, SEC filings, and fraud risk indicators provided.

Always respond with valid JSON matching the requested schema. Be specific and cite the data 
provided. If data is insufficient, say so explicitly rather than speculating."""

SINGLE_REPORT_PROMPT = """Analyse the following penny stock alert and sentiment data.

## Stock Alert
- Ticker: {ticker}
- Current Price: ${price:.4f}
- Price Change: {change_pct:+.2f}%
- Volume: {volume:,}
- Average Volume: {avg_volume:,}

## Sentiment Data
{sentiment_summary}

## SEC EDGAR Filings
{sec_summary}

## Fraud Risk Assessment
{fraud_summary}

## Additional Context from User
{user_context}

Respond with ONLY valid JSON in this exact schema:
{{
    "sentiment_score": <float -10 to 10>,
    "confidence": <float 0 to 1>,
    "bullish_signals": [<string>, ...],
    "bearish_signals": [<string>, ...],
    "risk_level": <int 1 to 5>,
    "fraud_risk": <"LOW" | "MEDIUM" | "HIGH" | "CRITICAL">,
    "recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">,
    "summary": "<2-3 sentence summary>",
    "key_factors": ["<most important factor 1>", "<factor 2>", "<factor 3>"]
}}"""

CONSENSUS_META_PROMPT = """You are a senior portfolio manager reviewing reports from multiple 
AI analysts about the same penny stock. Each analyst has independently assessed the stock. 
Your job is to synthesise their views into a consensus report.

## Individual Analyst Reports
{individual_reports}

Analyse the reports and respond with ONLY valid JSON:
{{
    "consensus_score": <float -10 to 10>,
    "agreement_level": <"STRONG" | "MODERATE" | "WEAK" | "DIVIDED">,
    "points_of_agreement": [<string>, ...],
    "points_of_disagreement": [<string>, ...],
    "strongest_bullish_argument": "<string>",
    "strongest_bearish_argument": "<string>",
    "consensus_recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">,
    "confidence": <float 0 to 1>,
    "summary": "<3-4 sentence synthesis>",
    "dissenting_view": "<brief note on any outlier opinion, or null>"
}}"""

# --- Research analysis prompt (for any asset, not just penny stocks) ---
RESEARCH_ANALYSIS_SYSTEM_PROMPT = """You are a senior financial analyst. You provide data-driven
analysis of any publicly traded asset. You have access to macro context, recent news, and
performance metrics. Always respond with valid JSON matching the requested schema.
Be specific and cite the data provided."""

RESEARCH_ANALYSIS_PROMPT = """Analyse the following asset.

## Asset Information
- Ticker: {ticker}
- Name: {name}
- Sector: {sector}
- Industry: {industry}
- Market Cap: {market_cap}
- Current Price: {current_price}
- P/E Ratio: {pe_ratio}
- Short Interest: {short_interest}

## Performance Metrics
{performance_summary}

## Macro Context
{macro_summary}

## Recent News Headlines
{news_summary}

## Additional Context from User
{user_context}

Respond with ONLY valid JSON in this exact schema:
{{
    "sentiment_score": <float -10 to 10>,
    "confidence": <float 0 to 1>,
    "bullish_signals": [<string>, ...],
    "bearish_signals": [<string>, ...],
    "risk_level": <int 1 to 5>,
    "fraud_risk": <"LOW" | "MEDIUM" | "HIGH" | "CRITICAL">,
    "recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">,
    "summary": "<2-3 sentence summary>",
    "key_factors": ["<most important factor 1>", "<factor 2>", "<factor 3>"]
}}"""

# --- Dashboard ---
DASHBOARD_PAGE_SIZE = 50  # Default pagination size

# --- Rate limiting ---
T212_ORDER_RATE_LIMIT = 2.0  # seconds between orders
T212_SUMMARY_RATE_LIMIT = 5.0  # seconds between account summary calls
ALPACA_REST_RATE_LIMIT = 200  # requests per minute
SEC_EDGAR_RATE_LIMIT = 10  # requests per second
