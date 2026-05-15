"""
Application-wide constants and magic values.
"""

# --- Exchanges ---
SUPPORTED_EXCHANGES = {"NASDAQ", "NYSE", "NYSE ARCA", "NYSE MKT"}

# --- Trading 212 ticker suffix mapping ---
# T212 uses format like AAPL_US_EQ for US equities
T212_TICKER_SUFFIX = "_US_EQ"

# --- Reddit subreddits to monitor ---
STOCK_SUBREDDITS = [
    "pennystocks",
    "wallstreetbets",
    "stocks",
    "investing",
    "smallstreetbets",
    "RobinHoodPennyStocks",
    "Shortsqueeze",
]

# --- ApeWisdom ---
APEWISDOM_API_BASE = "https://apewisdom.io/api/v1.0"

# --- Alpha Vantage ---
ALPHAVANTAGE_API_BASE = "https://www.alphavantage.co/query"

# --- SEC EDGAR ---
SEC_EDGAR_BASE = "https://efts.sec.gov/LATEST"
SEC_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_EDGAR_USER_AGENT = "FlorinTerminal admin@example.com"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

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

# --- LLM prompt templates ---

# ---------------------------------------------------------------------------
# Announcement Analysis — Form 8-K filings
# ---------------------------------------------------------------------------

ANNOUNCEMENT_SYSTEM_PROMPT = """You are a senior financial analyst specialising in corporate \
disclosures and SEC filings, with particular expertise in small-cap and micro-cap US equities.

Your task is to analyse one or more SEC Form 8-K filings and assess their impact on the \
company's stock. Form 8-Ks disclose material events: earnings, acquisitions, leadership \
changes, going-concern warnings, restructurings, and other significant corporate actions.

Score guidance (0–10 scale):
  0–2: Catastrophic news (bankruptcy filing, fraud disclosure, massive unexpected loss, \
delisting notice). Use only when evidence is unambiguous.
  3–4: Clearly negative (earnings miss, executive departure without succession plan, \
significant litigation).
  5:   Neutral or routine (administrative filings, minor amendments, expected reporting).
  6–7: Moderately positive (earnings beat, new contract, leadership hire).
  8–10: Transformational positive (major acquisition at premium, breakthrough partnership, \
regulatory approval for key product). Use only when evidence is strong and consistent.

Always respond with valid JSON matching the requested schema. Be specific and cite the \
filing content provided. If the filing content is insufficient to form a strong opinion, \
state that explicitly and assign a score near 5 with low confidence."""

ANNOUNCEMENT_USER_PROMPT = """Analyse the following Form 8-K filing(s) for {ticker}.

{filings_text}

## Additional Context from User
{user_context}

Respond with ONLY valid JSON in this exact schema:
{{
    "score": <float 0 to 10>,
    "confidence": <float 0 to 1>,
    "summary": "<2-3 sentence summary of the filing impact>",
    "key_points": ["<key finding 1>", "<key finding 2>", ...],
    "bullish_signals": [<string>, ...],
    "bearish_signals": [<string>, ...],
    "recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">
}}"""

# ---------------------------------------------------------------------------
# Sentiment Analysis — Web Search, Reddit, ApeWisdom, Alpha Vantage, News
# ---------------------------------------------------------------------------

SENTIMENT_SYSTEM_PROMPT = """You are a market sentiment analyst specialising in retail \
investor behaviour and news flow, with particular expertise in small-cap and micro-cap \
US equities.

Your task is to analyse social media posts, news articles, and web search results to \
gauge current market sentiment for a stock. Consider: volume of discussion, overall tone, \
credibility of sources, recency of posts, and potential signs of coordinated manipulation \
(many new accounts hyping a stock, bot-like posting patterns).

Score guidance (0–10 scale):
  0–2: Overwhelmingly negative/fearful — consistent negative coverage, panic selling \
discussion, credible warnings. Use only when evidence is strong and consistent.
  3–4: Mostly negative — more bearish than bullish signals, negative news coverage.
  5:   Neutral/mixed — balanced discussion, no strong directional signal.
  6–7: Mostly positive — bullish social sentiment, positive news, growing interest.
  8–10: Overwhelmingly positive/euphoric — extreme hype, unanimous bullishness, viral \
attention. Use only when evidence is strong. Note: extreme euphoria can itself be a \
warning sign of pump-and-dump activity.

Always respond with valid JSON matching the requested schema. Be specific and cite the \
data provided. If data is sparse, state that explicitly and assign a score near 5 with \
low confidence."""

SENTIMENT_USER_PROMPT = """Analyse the following sentiment data for {ticker}.

## Stock Context
- Current Price: ${price:.4f}
- Price Change: {change_pct:+.2f}%
- Volume: {volume:,}
- Average Volume: {avg_volume:,}

## Sentiment Data
{sentiment_summary}

## Additional Context from User
{user_context}

Respond with ONLY valid JSON in this exact schema:
{{
    "score": <float 0 to 10>,
    "confidence": <float 0 to 1>,
    "summary": "<2-3 sentence summary of market sentiment>",
    "key_points": ["<key finding 1>", "<key finding 2>", ...],
    "bullish_signals": [<string>, ...],
    "bearish_signals": [<string>, ...],
    "recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">
}}"""

# ---------------------------------------------------------------------------
# Consensus Leader — Synthesise multiple analyst reports
# ---------------------------------------------------------------------------

CONSENSUS_LEADER_SYSTEM_PROMPT = """You are a chief investment officer reviewing reports \
from multiple AI analysts about the same stock. Each analyst has independently analysed \
the same data and produced their own assessment.

Your job is to synthesise their individual reports into a single consensus view. You must:
1. Identify areas of agreement across analysts.
2. Flag significant disagreements and explain possible reasons.
3. Weigh analysts by their stated confidence levels.
4. Produce a consensus score, summary, and recommendation.
5. Note the variance in analyst opinion — this is critical information for the end user.

If analysts are largely in agreement, state that clearly. If opinions diverge significantly, \
explain the divergence and which position you find most convincing and why.

Always respond with valid JSON matching the requested schema."""

CONSENSUS_LEADER_USER_PROMPT = """Synthesise the following {analysis_type} analysis reports \
for {ticker} into a consensus view.

## Individual Analyst Reports
{individual_reports}

Respond with ONLY valid JSON in this exact schema:
{{
    "score": <float 0 to 10>,
    "confidence": <float 0 to 1>,
    "summary": "<3-4 sentence consensus synthesis>",
    "key_points": ["<consensus finding 1>", "<consensus finding 2>", ...],
    "bullish_signals": [<string>, ...],
    "bearish_signals": [<string>, ...],
    "recommendation": <"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "STRONG_AVOID">
}}"""

# ---------------------------------------------------------------------------
# Legacy / Research Analysis — kept for the research tab
# ---------------------------------------------------------------------------

# --- Research analysis prompt (for any asset) ---
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
