# Penny Stock Sentinel — Claude Code Implementation Plan

## Answers to Your Questions

### 1. Free Market Data at Minute-Level Frequency

**Trading 212's API does NOT provide market data prices.** It only exposes account info, positions, orders, and instrument metadata. You need a separate data source entirely.

**Best free option: Alpaca Markets (Free/Basic plan)**
- Real-time IEX exchange data via WebSocket (minute bars, trades, quotes) — completely free
- 200 API requests/minute for historical data
- Caveat: IEX is a single exchange (~2-5% of total volume for most stocks). For penny stocks this matters less since many trade predominantly on a few venues
- You get streaming minute bars via `wss://stream.data.alpaca.markets/v2/iex` with `"bars": ["*"]` wildcard subscription
- Historical 15-min delayed SIP data is also free (good enough for detecting 5%+ moves)
- No credit card required — just sign up at alpaca.markets

**Other free options (as supplements/fallbacks):**
- **Twelve Data**: Free tier = 8 API calls/min, 800/day. Supports 1-min bars. Too rate-limited for scanning 800+ tickers but useful as a secondary source for individual stock deep-dives
- **Financial Modeling Prep (FMP)**: Free tier includes 1-min historical bars but capped at ~250 calls/day. Their Stock Screener endpoint can filter by price < $5 in a single call
- **Alpha Vantage**: Free tier = 25 requests/day (essentially useless for this use case, but good for supplementary technical indicators)
- **Yahoo Finance (yfinance)**: Free but unreliable — aggressively rate-limits after ~950 tickers and frequently breaks

**Recommended architecture**: Alpaca free tier as the primary real-time scanner (WebSocket streaming minute bars for all tickers). Use FMP free tier for the initial penny stock universe discovery (list all stocks < $5). Fall back to Polygon.io ($29/mo) if Alpaca IEX coverage proves insufficient for penny stock detection.

### 2. Local LLM Alternatives to FinBERT

FinBERT (2019) is outdated — it's a BERT classifier that only outputs positive/negative/neutral labels with no reasoning, no nuance, and no ability to synthesise information. Here's the modern landscape:

**For the "offline LLM" slot, the clear winner is running a general-purpose LLM via Ollama with financial prompting:**

| Model | Size | RAM Needed | Approach | Quality |
|-------|------|-----------|----------|---------|
| **Llama 3.2 8B** (via Ollama) | 4.7GB | 8GB | Few-shot prompted for financial analysis | ⭐⭐⭐⭐⭐ — outperforms FinBERT on every benchmark |
| **Mistral 7B v0.3** (via Ollama) | 4.1GB | 8GB | Strong reasoning, good at structured output | ⭐⭐⭐⭐ |
| **FinGPT v3.3** (Llama 2 13B + LoRA) | ~7GB | 16GB | Purpose-built financial sentiment, F1 up to 87.6% | ⭐⭐⭐⭐ — best if you have 16GB RAM |
| **Qwen 2.5 7B** (via Ollama) | 4.4GB | 8GB | Strong multilingual + reasoning | ⭐⭐⭐⭐ |
| FinBERT (legacy) | 440MB | 2GB | Classification only (pos/neg/neutral) | ⭐⭐ — no reasoning capability |

**Recommendation**: Use **Llama 3.2 8B via Ollama** as the default offline model. It can generate full analytical reports (not just labels), understands financial context, handles long inputs, and runs on any modern laptop. Keep FinBERT available as a fast "sentiment score only" option for batch processing (it processes 100 texts in seconds vs. minutes for an LLM). The modular design means you can swap in FinGPT or any future model trivially.

A research paper from ICAIF 2024 confirmed that Llama 3 70B outperformed FinBERT, GPT-4, and all other models on FOMC financial sentiment classification. The 8B version captures most of this capability at a fraction of the resource cost.

### 3. Python Version

**Use Python 3.12.** Here's why:

All critical packages support 3.12 with full battle-testing:
- `transformers` 5.3.0: supports 3.10–3.14
- `torch` (PyTorch): full 3.12 and 3.13 support
- `python-telegram-bot` / `pyTelegramBotAPI`: tested on 3.9–3.13
- `aiogram` (async Telegram): requires 3.10+
- `aiohttp`: ✅ 3.13 compatible
- `praw` (Reddit): ✅ works on 3.12+
- `pandas`, `numpy`, `scikit-learn`: all ✅
- `fastapi` + `uvicorn`: all ✅
- `sqlalchemy`: ✅

Python 3.13 is also fully supported now, but 3.12 is the "mature sweet spot" — every edge case has been found and fixed. 3.13 occasionally has minor wheel availability issues with niche packages. **Go with 3.12 for zero-friction setup; upgrade to 3.13 later if desired.**

---

## Implementation Plan for Claude Code

### Project Name: `penny-stock-sentinel`

### Architecture Overview

```
penny-stock-sentinel/
├── config/
│   ├── settings.py              # Pydantic Settings (env vars, defaults)
│   └── constants.py             # Magic numbers, ticker suffixes, etc.
├── core/
│   ├── __init__.py
│   ├── events.py                # Event bus (asyncio queues)
│   └── models.py                # Pydantic data models (Stock, Alert, Trade, Report)
├── data/
│   ├── __init__.py
│   ├── base.py                  # Abstract MarketDataProvider interface
│   ├── alpaca_provider.py       # Alpaca free tier (default)
│   ├── polygon_provider.py      # Polygon.io (paid fallback)
│   ├── fmp_provider.py          # FMP (universe discovery)
│   └── t212_provider.py         # Trading212 position/price data
├── scanner/
│   ├── __init__.py
│   ├── base.py                  # Abstract Scanner interface
│   ├── momentum_scanner.py      # Detects >X% moves in Y timeframe
│   └── universe.py              # Manages penny stock universe (NASDAQ+NYSE, <$5)
├── sentiment/
│   ├── __init__.py
│   ├── base.py                  # Abstract SentimentSource interface
│   ├── reddit_source.py         # PRAW-based Reddit scraper
│   ├── stocktwits_source.py     # StockTwits API
│   ├── sec_edgar_source.py      # SEC EDGAR (Form 4, 8-K, insider trades)
│   ├── news_source.py           # Alpha Vantage / FMP news
│   └── aggregator.py            # Combines all sentiment sources
├── analysis/
│   ├── __init__.py
│   ├── base.py                  # Abstract LLMAnalyser interface
│   ├── ollama_analyser.py       # Local LLM via Ollama (Llama 3.2 8B)
│   ├── groq_analyser.py         # Groq API (Llama 4 Scout)
│   ├── gemini_analyser.py       # Google Gemini API
│   ├── claude_analyser.py       # Anthropic Claude API
│   ├── finbert_analyser.py      # FinBERT (fast batch sentiment scoring)
│   ├── report_generator.py      # Single-LLM report mode
│   ├── consensus_generator.py   # Multi-LLM consensus mode
│   └── fraud_detector.py        # Pump-and-dump / fraud risk scoring
├── broker/
│   ├── __init__.py
│   ├── base.py                  # Abstract Broker interface
│   ├── trading212.py            # Trading 212 API client
│   └── paper_broker.py          # Paper trading (for testing)
├── telegram_bot/
│   ├── __init__.py
│   ├── bot.py                   # Main bot setup (aiogram)
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── alerts.py            # Incoming alert display + BUY/DENY buttons
│   │   ├── positions.py         # Position monitoring + SELL buttons
│   │   ├── commands.py          # /status, /balance, /settings, /kill
│   │   └── callbacks.py         # Inline button callback handlers
│   └── formatters.py            # Message formatting (Markdown)
├── dashboard/
│   ├── __init__.py
│   ├── app.py                   # FastAPI application
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── positions.py         # GET /api/positions
│   │   ├── universe.py          # GET /api/universe, CRUD settings
│   │   ├── reports.py           # GET /api/reports/{id}
│   │   ├── trades.py            # GET /api/trades (history)
│   │   ├── account.py           # GET /api/account (T212 summary)
│   │   ├── orders.py            # POST /api/orders (buy/sell/stoploss)
│   │   └── stats.py             # GET /api/stats (P&L, win rate, etc.)
│   ├── static/                  # Built React app served by FastAPI
│   └── ws.py                    # WebSocket for real-time dashboard updates
├── dashboard_ui/                # React frontend (separate build step)
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx    # Overview: positions + P&L + alerts
│   │   │   ├── Universe.jsx     # All penny stocks + filters
│   │   │   ├── Reports.jsx      # Browse all generated reports
│   │   │   ├── TradeHistory.jsx # All executed trades
│   │   │   ├── Account.jsx      # T212 account overview + order management
│   │   │   ├── Settings.jsx     # Configure thresholds, LLM prefs, etc.
│   │   │   └── Stats.jsx        # Trading statistics + charts
│   │   ├── components/
│   │   │   ├── PositionCard.jsx
│   │   │   ├── StockTable.jsx
│   │   │   ├── ReportViewer.jsx
│   │   │   ├── TradeForm.jsx
│   │   │   ├── StatsCharts.jsx
│   │   │   └── AlertFeed.jsx
│   │   └── hooks/
│   │       ├── useWebSocket.js
│   │       └── useApi.js
│   └── vite.config.js
├── db/
│   ├── __init__.py
│   ├── database.py              # SQLAlchemy async engine + session
│   ├── models.py                # ORM models (Trade, Report, Alert, Position, Setting)
│   └── migrations/              # Alembic migrations
├── tests/
│   ├── test_scanner.py
│   ├── test_sentiment.py
│   ├── test_analysis.py
│   ├── test_broker.py
│   └── test_fraud.py
├── main.py                      # Entry point: starts all services
├── pyproject.toml               # Project config + dependencies
├── docker-compose.yml           # DB + app containers
├── .env.example                 # Template for secrets
└── README.md
```

---

### Phase 1 — Foundation (Estimated: 2–3 days)

**Goal**: Project skeleton, config, data models, database, and abstract interfaces.

#### Tasks:
1. **Project setup**
   - Initialise `pyproject.toml` with all dependencies
   - Python 3.12 virtual environment
   - Pre-commit hooks (ruff, mypy)

2. **Configuration system** (`config/settings.py`)
   - Pydantic `BaseSettings` loading from `.env`
   - All API keys, thresholds, feature flags
   - Settings for: price threshold ($5 default), momentum threshold (5% default), scan interval, LLM mode (single/consensus), active LLM providers

3. **Data models** (`core/models.py`)
   - Pydantic models: `StockQuote`, `SentimentData`, `AnalysisReport`, `TradeRecord`, `Position`, `AlertSignal`, `FraudRiskScore`
   - Ensure all models are serialisable (JSON for API, Markdown for Telegram)

4. **Database** (`db/`)
   - SQLAlchemy 2.0 async with SQLite (aiosqlite)
   - Tables: `trades`, `reports`, `alerts`, `positions`, `settings`, `universe_cache`
   - Alembic migration setup

5. **Abstract interfaces** (all `base.py` files)
   - `MarketDataProvider(ABC)`: `async get_snapshot()`, `async stream_bars()`, `async get_historical()`
   - `SentimentSource(ABC)`: `async fetch_sentiment(ticker: str) -> SentimentData`
   - `LLMAnalyser(ABC)`: `async analyse(ticker: str, data: SentimentData) -> AnalysisReport`
   - `Broker(ABC)`: `async buy()`, `async sell()`, `async get_positions()`, `async get_account()`
   - `Scanner(ABC)`: `async scan() -> list[AlertSignal]`

6. **Event bus** (`core/events.py`)
   - Simple `asyncio.Queue`-based pub/sub
   - Events: `MOMENTUM_ALERT`, `REPORT_READY`, `TRADE_EXECUTED`, `POSITION_UPDATE`

#### Dependencies (pyproject.toml):
```toml
[project]
name = "penny-stock-sentinel"
requires-python = ">=3.12"
dependencies = [
    # Core
    "pydantic>=2.6",
    "pydantic-settings>=2.2",

    # Async
    "aiohttp>=3.9",
    "asyncio>=3.4",

    # Database
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.13",

    # Market Data
    "alpaca-py>=0.28",         # Alpaca SDK
    "polygon-api-client>=1.14", # Polygon fallback

    # Sentiment
    "praw>=7.7",               # Reddit
    "aiohttp>=3.9",            # StockTwits + SEC EDGAR

    # LLM
    "transformers>=4.40",      # FinBERT
    "torch>=2.4",              # PyTorch for FinBERT
    "ollama>=0.3",             # Local LLM client
    "anthropic>=0.30",         # Claude API
    "google-generativeai>=0.5",# Gemini API
    "groq>=0.9",               # Groq API

    # Telegram
    "aiogram>=3.10",           # Async Telegram bot framework

    # Dashboard
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "websockets>=12.0",

    # Utilities
    "python-dotenv>=1.0",
    "structlog>=24.1",         # Structured logging
    "rich>=13.7",              # Pretty console output
    "httpx>=0.27",             # Async HTTP client
]
```

---

### Phase 2 — Market Data & Scanner (Estimated: 2–3 days)

**Goal**: Real-time penny stock scanning that detects >X% moves.

#### Tasks:
1. **Universe manager** (`scanner/universe.py`)
   - On startup, fetch all instruments from Trading 212 API (`GET /api/v0/equity/metadata/instruments`)
   - Cross-reference with FMP Stock Screener to get current prices
   - Filter: NASDAQ + NYSE, price < configurable threshold (default $5)
   - Cache in SQLite, refresh daily at market open
   - Store T212-specific ticker format (e.g., `AAPL_US_EQ`) alongside standard tickers

2. **Alpaca data provider** (`data/alpaca_provider.py`)
   - Implement `MarketDataProvider` interface
   - WebSocket connection to `wss://stream.data.alpaca.markets/v2/iex`
   - Subscribe to minute bars for all universe tickers (split into batches of ~500 to stay under 16KB WebSocket message limit)
   - Maintain in-memory price cache: `{ticker: {last_price, open_price, prev_close, volume, timestamp}}`
   - Fallback: REST polling of `/v2/stocks/snapshots` every 2 minutes for tickers where WebSocket data is sparse

3. **Polygon provider** (`data/polygon_provider.py`)
   - Implement same interface using Polygon `GET /v2/snapshot/locale/us/markets/stocks/tickers`
   - Single call returns all tickers with `todaysChangePerc` field
   - Used if Alpaca IEX proves insufficient

4. **Momentum scanner** (`scanner/momentum_scanner.py`)
   - Consumes price updates from data provider
   - Calculates % change from: (a) today's open, (b) previous close, (c) rolling N-minute low
   - Fires `MOMENTUM_ALERT` event when threshold exceeded
   - Cooldown: don't re-alert same ticker within configurable window (default 30 mins)
   - Filters: minimum volume threshold, exclude tickers with no trades in last 5 mins

---

### Phase 3 — Sentiment Scraping (Estimated: 2–3 days)

**Goal**: On alert, gather sentiment data from multiple sources.

#### Tasks:
1. **Reddit source** (`sentiment/reddit_source.py`)
   - PRAW async wrapper (praw is sync; wrap with `asyncio.to_thread`)
   - Search subreddits: r/pennystocks, r/wallstreetbets, r/stocks, r/investing, r/smallstreetbets
   - Search queries: ticker symbol, company name
   - Extract: post titles, top comments, upvote ratios, timestamps, flair
   - Rate limit: 100 req/min (plenty)
   - Return: list of `RedditPost(title, body, score, num_comments, sentiment_hint, url, timestamp)`

2. **StockTwits source** (`sentiment/stocktwits_source.py`)
   - `GET https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json`
   - Extract: message text, bullish/bearish label, timestamp, likes
   - Pre-labelled sentiment = gold for training/validation
   - Return: `StockTwitsSentiment(bullish_count, bearish_count, total, messages)`

3. **SEC EDGAR source** (`sentiment/sec_edgar_source.py`)
   - `GET https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&startdt=...&enddt=...`
   - Focus on: Form 4 (insider buying/selling), Form 8-K (material events), 13F (institutional holdings)
   - Free, no auth, 10 req/sec
   - Return: `SECFilings(insider_buys, insider_sells, recent_8k_events, institutional_changes)`

4. **News source** (`sentiment/news_source.py`)
   - Alpha Vantage News Sentiment endpoint (free tier)
   - FMP stock news endpoint
   - Return: `NewsItems(articles: list[Article])` with headline, source, timestamp, relevance score

5. **Sentiment aggregator** (`sentiment/aggregator.py`)
   - Orchestrates all sources concurrently via `asyncio.gather()`
   - Combines into unified `SentimentData` object
   - Handles source failures gracefully (partial data is fine)
   - Adds metadata: data freshness, source count, confidence level

---

### Phase 4 — LLM Analysis Engine (Estimated: 3–4 days)

**Goal**: Modular LLM system with single-report and consensus modes.

#### Tasks:
1. **FinBERT analyser** (`analysis/finbert_analyser.py`)
   - Load `ProsusAI/finbert` via HuggingFace Transformers
   - Batch process all text snippets (Reddit titles, news headlines, StockTwits messages)
   - Return aggregate sentiment scores: % positive, % negative, % neutral
   - Fast (~100 texts/second on CPU) — used as a preprocessing step for all modes

2. **Ollama analyser** (`analysis/ollama_analyser.py`)
   - Connect to local Ollama instance (`http://localhost:11434`)
   - Default model: `llama3.2:8b` (configurable)
   - Structured prompt template requesting JSON output:
     ```
     Analyse this penny stock based on the provided data.
     Return JSON with: sentiment_score (-10 to 10), confidence (0-1),
     bullish_signals [], bearish_signals [], risk_level (1-5),
     fraud_risk_assessment, recommendation (STRONG_BUY/BUY/HOLD/AVOID),
     summary (2-3 sentences)
     ```
   - Timeout: 60 seconds (local inference can be slow)

3. **Groq analyser** (`analysis/groq_analyser.py`)
   - Groq SDK with Llama 4 Scout model
   - Same prompt template as Ollama
   - Sub-second response time, ~$0.0004/report

4. **Gemini analyser** (`analysis/gemini_analyser.py`)
   - Google Generative AI SDK
   - Gemini 2.5 Flash-Lite (free tier handles this volume)
   - Same prompt template

5. **Claude analyser** (`analysis/claude_analyser.py`)
   - Anthropic SDK with Claude Haiku 4.5
   - Same prompt template
   - Higher quality analysis for ambiguous cases

6. **Single-LLM report generator** (`analysis/report_generator.py`)
   - Mode 1: Takes sentiment data + fraud risk → sends to configured default LLM
   - Generates formatted report (Markdown)
   - Includes: stock summary, sentiment breakdown, risk assessment, LLM recommendation

7. **Multi-LLM consensus generator** (`analysis/consensus_generator.py`)
   - Mode 2: Sends sentiment data to ALL configured LLMs concurrently
   - Collects individual reports
   - Sends all reports to a designated "meta-analyser" LLM (configurable, default: Claude)
   - Meta-prompt: "Here are reports from 4 different analysts. Summarise where they agree, where they disagree, highlight the strongest arguments, and provide a consensus recommendation."
   - Output: ConsensusReport with individual reports + meta-analysis

8. **Fraud detector** (`analysis/fraud_detector.py`)
   - Rule-based + LLM-assisted fraud risk scoring
   - Signals checked:
     - Sudden volume spike (>10x average) with no news
     - Reddit/StockTwits post age < 24 hours from new/low-karma accounts
     - No SEC filings in 90+ days
     - Company has no revenue / shell company indicators
     - Price < $1 (sub-penny = highest manipulation risk)
     - Coordinated posting patterns (many posts in short window)
   - Combine into `FraudRiskScore(score: float, flags: list[str], confidence: float)`
   - Feeds into all LLM analysis prompts as additional context

---

### Phase 5 — Trading 212 Broker Integration (Estimated: 2 days)

**Goal**: Execute trades and monitor positions via T212 API.

#### Tasks:
1. **Trading 212 client** (`broker/trading212.py`)
   - Implement `Broker` interface
   - Auth: HTTP Basic (API key:secret, Base64 encoded)
   - Endpoints:
     - `GET /api/v0/equity/account/summary` — account overview (1 req/5s)
     - `GET /api/v0/equity/portfolio` — all open positions
     - `POST /api/v0/equity/orders/market` — market buy/sell
     - `POST /api/v0/equity/orders/limit` — limit orders
     - `POST /api/v0/equity/orders/stop` — stop-loss orders
     - `DELETE /api/v0/equity/orders/{id}` — cancel pending orders
     - `GET /api/v0/equity/history/orders` — trade history
   - **Critical**: T212 API is not idempotent — implement request deduplication (track order IDs in DB, check before sending)
   - Ticker mapping: convert standard tickers to T212 format (e.g., `AAPL` → `AAPL_US_EQ`)
   - Rate limiter: respect per-endpoint limits (1 order/2s, 1 summary/5s)
   - Error handling: retry with exponential backoff, circuit breaker pattern

2. **Paper broker** (`broker/paper_broker.py`)
   - Simulates T212 API for testing
   - Tracks virtual positions, P&L, trade history
   - Uses real market data for price simulation

3. **Position monitor** (in `main.py` background task)
   - Poll T212 positions every 30 seconds during market hours
   - Calculate unrealised P&L using market data provider prices
   - Check stop-loss thresholds (configurable per position)
   - Fire `POSITION_UPDATE` events for Telegram and dashboard

---

### Phase 6 — Telegram Bot (Estimated: 2–3 days)

**Goal**: Full mobile trading interface via Telegram.

#### Tasks:
1. **Bot setup** (`telegram_bot/bot.py`)
   - aiogram 3.x framework (fully async, native asyncio)
   - Register with BotFather, get token
   - Restrict to your chat ID only (security)
   - Start polling on app startup

2. **Alert handler** (`telegram_bot/handlers/alerts.py`)
   - On `REPORT_READY` event, format and send to Telegram
   - Message format:
     ```
     🚀 ALERT: $TICKER +7.2% | $2.34
     ━━━━━━━━━━━━━━━━━━━━━
     📊 Sentiment: 7.2/10 (Bullish)
     🔍 Sources: Reddit(12), StockTwits(45), SEC(2)
     ⚠️ Fraud Risk: LOW (1.2/5)
     🤖 Recommendation: BUY

     Key Signals:
     • Reddit: Heavy discussion on r/pennystocks
     • StockTwits: 78% bullish (45 messages)
     • SEC: Insider bought 50K shares yesterday

     [Full Report] [📈 BUY] [❌ DENY]
     ```
   - Inline keyboard: BUY, DENY, VIEW FULL REPORT buttons

3. **Trade execution callbacks** (`telegram_bot/handlers/callbacks.py`)
   - BUY → confirmation step: "Buy $TICKER @ ~$2.34? Qty: X shares ($100 position size). [CONFIRM] [CANCEL]"
   - CONFIRM → execute via broker, update message with result
   - SELL → same flow for open positions

4. **Position monitoring** (`telegram_bot/handlers/positions.py`)
   - `/positions` command: list all open positions with P&L
   - Each position has SELL and SET STOP-LOSS buttons
   - Proactive alerts: push notification when position hits ±10% or stop-loss

5. **Commands** (`telegram_bot/handlers/commands.py`)
   - `/start` — welcome + status
   - `/status` — system health (scanner running, data sources up, etc.)
   - `/balance` — T212 account cash + invested value
   - `/positions` — open positions summary
   - `/settings` — view/edit scan thresholds
   - `/mode single|consensus` — switch LLM analysis mode
   - `/kill` — emergency: cancel all pending orders, pause scanner

---

### Phase 7 — Web Dashboard (Estimated: 4–5 days)

**Goal**: Full-featured dashboard for home use alongside Telegram.

#### Tasks:
1. **FastAPI backend** (`dashboard/app.py`)
   - REST API + WebSocket for real-time updates
   - Serves React static build
   - Shares database and event bus with main application

2. **API routes** (`dashboard/routes/`)
   - `GET /api/positions` — all open positions with live P&L
   - `GET /api/universe` — penny stock universe with current prices, % change
   - `GET /api/universe/settings` — scanner config (price threshold, etc.)
   - `PUT /api/universe/settings` — update config
   - `GET /api/reports` — paginated list of all generated reports
   - `GET /api/reports/{id}` — full report detail
   - `GET /api/trades` — all executed trades (filterable by date, ticker, outcome)
   - `GET /api/account` — T212 account summary
   - `POST /api/orders/buy` — place buy order
   - `POST /api/orders/sell` — place sell order
   - `POST /api/orders/stoploss` — set stop-loss
   - `DELETE /api/orders/{id}` — cancel order
   - `GET /api/stats` — trading statistics (win rate, avg P&L, Sharpe, etc.)

3. **WebSocket** (`dashboard/ws.py`)
   - Real-time push: price updates, new alerts, position changes, trade executions
   - Client subscribes to channels: `prices`, `alerts`, `positions`

4. **React frontend** (`dashboard_ui/`)
   - **Vite + React 18 + TailwindCSS**
   - Pages:
     - **Dashboard** (home): Live positions grid, P&L chart, recent alerts feed, account summary card
     - **Universe**: Sortable/filterable table of all penny stocks. Columns: ticker, price, % change, volume, sector. Click → detail view with mini-chart
     - **Settings**: Configure price threshold, momentum threshold, scan interval, LLM mode toggle (single/consensus), enable/disable individual LLMs, position size, stop-loss defaults
     - **Reports**: Searchable list of all generated reports. Click → full report with sentiment breakdown, LLM analysis, fraud risk assessment
     - **Trade History**: Table of all executed trades. Columns: date, ticker, side, price, quantity, P&L, status. Export to CSV
     - **Account**: T212 account mirror — cash balance, invested value, total value, pending orders with cancel buttons, trade management (buy/sell/stop-loss forms)
     - **Statistics**: Win rate, total P&L, average hold time, best/worst trades, P&L by day/week/month (Recharts), Sharpe ratio, max drawdown

---

### Phase 8 — Integration & Orchestration (Estimated: 2 days)

**Goal**: Wire everything together in `main.py`.

```python
# main.py (simplified)
async def main():
    # 1. Load config
    settings = Settings()

    # 2. Initialise database
    db = await init_database(settings.database_url)

    # 3. Initialise event bus
    event_bus = EventBus()

    # 4. Initialise components (all implement abstract interfaces)
    data_provider = AlpacaProvider(settings)  # swappable
    broker = Trading212Broker(settings)        # swappable
    scanner = MomentumScanner(data_provider, settings)
    sentiment_agg = SentimentAggregator([
        RedditSource(settings),
        StockTwitsSource(settings),
        SECEdgarSource(settings),
        NewsSource(settings),
    ])

    # 5. Initialise LLM analysers
    analysers = {
        "ollama": OllamaAnalyser(settings),
        "groq": GroqAnalyser(settings),
        "gemini": GeminiAnalyser(settings),
        "claude": ClaudeAnalyser(settings),
        "finbert": FinBERTAnalyser(settings),
    }
    report_gen = ReportGenerator(analysers, settings)
    consensus_gen = ConsensusGenerator(analysers, settings)
    fraud_detector = FraudDetector(settings)

    # 6. Start services
    await asyncio.gather(
        scanner.run(event_bus),           # Continuous scanning
        alert_pipeline(event_bus, ...),   # React to alerts
        position_monitor(broker, ...),     # Monitor positions
        telegram_bot.start_polling(),      # Telegram interface
        dashboard_server.serve(),          # Web dashboard
    )

async def alert_pipeline(event_bus, sentiment_agg, report_gen,
                          consensus_gen, fraud_detector, telegram, db):
    """React to momentum alerts."""
    while True:
        alert = await event_bus.get("MOMENTUM_ALERT")

        # 1. Scrape sentiment
        sentiment = await sentiment_agg.fetch(alert.ticker)

        # 2. Assess fraud risk
        fraud_risk = await fraud_detector.assess(alert.ticker, sentiment)

        # 3. Generate report (single or consensus mode based on settings)
        if settings.llm_mode == "consensus":
            report = await consensus_gen.generate(alert, sentiment, fraud_risk)
        else:
            report = await report_gen.generate(alert, sentiment, fraud_risk)

        # 4. Save to database
        await db.save_report(report)

        # 5. Push to Telegram + Dashboard
        await event_bus.put("REPORT_READY", report)
```

---

### Phase 9 — Testing & Hardening (Estimated: 2–3 days)

1. **Unit tests**: Each module independently (mock external APIs)
2. **Integration tests**: Full pipeline with paper broker
3. **Paper trading period**: Run for 1–2 weeks with paper broker, validate signal quality
4. **Error handling**: Circuit breakers on all external APIs, graceful degradation
5. **Logging**: structlog with JSON output, log all trades and decisions
6. **Monitoring**: Health check endpoint, Telegram `/status` command
7. **Security**: API keys in `.env` only, Telegram chat ID whitelist, T212 IP restriction

---

### Estimated Monthly Running Costs

| Component | Cost |
|-----------|------|
| Market data (Alpaca free) | £0 |
| Reddit (PRAW free) | £0 |
| StockTwits (free) | £0 |
| SEC EDGAR (free) | £0 |
| Telegram Bot API | £0 |
| Groq API (~50 reports/day) | ~£1 |
| Gemini (free tier) | £0 |
| Claude Haiku (consensus mode) | ~£5 |
| Ollama (local) | £0 |
| VPS (Hetzner CX22) | ~£5 |
| **Total** | **~£11/month** |
| Polygon.io (if needed) | +£25/month |

---

### Implementation Order for Claude Code

Execute phases in this order — each phase is independently testable:

```
Phase 1 → Phase 2 → Phase 5 → Phase 3 → Phase 4 → Phase 6 → Phase 7 → Phase 8 → Phase 9
 (base)   (scanner)  (broker)  (sentiment) (LLMs)  (telegram) (dashboard) (glue)   (test)
```

Rationale: Get the data flowing and broker connected first (you can manually test trades). Then add intelligence (sentiment + LLMs). Then add the interfaces (Telegram + Dashboard). Finally, wire it all together and test.

Each phase should be its own git branch, merged to `main` after testing. Claude Code should implement one phase at a time with tests before moving on.