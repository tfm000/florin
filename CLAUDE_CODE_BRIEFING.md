# CLAUDE_CODE_BRIEFING.md

## What This Project Is

**Penny Stock Sentinel** is a personal AI-powered penny stock sentiment screening and trading tool for a UK-based quant with a financial maths/stats background and ML masters. It monitors all penny stocks on NASDAQ + NYSE, detects momentum moves (>5%), scrapes sentiment from Reddit/StockTwits/SEC EDGAR, generates AI analysis reports via multiple LLMs, delivers alerts via Telegram with BUY/DENY buttons, and executes trades via the Trading 212 API. A web dashboard provides full monitoring when at home.

The user trades via a **Trading 212 Stocks and Shares ISA** and is aware that T212's terms prohibit algorithmic trading — they accept this risk. Do not second-guess this decision or add warnings about it.

---

## What Has Been Completed (Phase 1 — Foundation)

Phase 1 is **done**. The following files exist and are production-ready:

### Configuration
- **`config/settings.py`** — Pydantic `BaseSettings` with defaults, overridden by database settings table (configured via dashboard). Includes typed enums for LLM mode (single/consensus), LLM providers, T212 environment (demo/live), Alpaca feed (iex/sip). Has derived properties like `t212_base_url`, `alpaca_data_ws_url`, `get_enabled_llm_providers()`. Singleton via `get_settings()`.
- **`config/constants.py`** — All magic values: subreddit list, API base URLs, SEC EDGAR endpoints, fraud detection thresholds, LLM prompt templates (ANALYSIS_SYSTEM_PROMPT, SINGLE_REPORT_PROMPT, CONSENSUS_META_PROMPT), rate limits, T212 ticker suffix conventions.

### Core Data Models (`core/models.py`)
27 Pydantic models covering the entire data flow:
- **Market data**: `StockQuote`, `StockInfo`, `BarData`
- **Alerts**: `AlertSignal` (with `AlertSource` enum)
- **Sentiment**: `RedditPost`, `StockTwitsMessage`, `SECFiling`, `NewsArticle`, `SentimentData` (aggregated, with `.to_summary()` method for LLM prompts)
- **Fraud**: `FraudRiskScore` (with `.to_summary()`)
- **LLM Analysis**: `LLMAnalysis`, `AnalysisReport`, `ConsensusAnalysis`
- **Trading**: `Position`, `TradeRecord`, `AccountSummary`, `OrderRequest`, `OrderResult`
- **Statistics**: `TradingStats`
- **Enums**: `Exchange`, `Side`, `OrderType`, `OrderStatus`, `Recommendation`, `FraudRisk`, `AgreementLevel`

### Event Bus (`core/events.py`)
Async pub/sub using `asyncio.Queue`. Typed `EventType` enum with events: `MOMENTUM_ALERT`, `SENTIMENT_COLLECTED`, `REPORT_READY`, `TRADE_EXECUTED`, `TRADE_FAILED`, `POSITION_UPDATE`, `POSITION_STOP_LOSS`, `ACCOUNT_UPDATE`, `SCANNER_STATUS`, `SYSTEM_ERROR`, `SETTINGS_CHANGED`. Supports multiple subscribers per event type, global subscribers, backpressure (configurable queue size), and async iteration.

### Abstract Interfaces (all `base.py` files)
Every module has a fully defined ABC that concrete implementations must follow:
- **`data/base.py`** → `MarketDataProvider`: `connect()`, `disconnect()`, `get_snapshot()`, `get_all_snapshots()`, `stream_bars()`, `get_historical_bars()`, `get_instruments()`. Async context manager.
- **`scanner/base.py`** → `Scanner`: `run(event_bus)`, `scan_once()`, `stop()`, `is_running`.
- **`sentiment/base.py`** → `SentimentSource`: `name`, `fetch(ticker, company_name)`, `health_check()`.
- **`analysis/base.py`** → `LLMAnalyser`: `provider_name`, `model_name`, `analyse(alert, sentiment, fraud_risk)`, `health_check()`.
- **`broker/base.py`** → `Broker`: `name`, `is_live`, `get_account_summary()`, `get_positions()`, `get_position(ticker)`, `place_order(order)`, `cancel_order(id)`, `get_pending_orders()`, `get_trade_history()`, `connect()`, `disconnect()`, `health_check()`. Async context manager.

### Database (`db/`)
- **`db/database.py`** — SQLAlchemy 2.0 async engine with `aiosqlite`. `Database` class with `init()`, `close()`, `session()` context manager. Creates all tables on startup.
- **`db/models.py`** — 7 ORM models: `TradeORM`, `ReportORM`, `AlertORM`, `UniverseStockORM`, `SettingORM`, `TelegramMessageORM`. All have auto-generated IDs, timestamps, and appropriate indexes.

### Logging (`core/logging.py`)
Structlog configuration: colourful console in dev, JSON in production. Quietens noisy library loggers.

### Entry Point (`main.py`)
`Sentinel` orchestrator class with `start()`, `shutdown()`, signal handling (SIGINT/SIGTERM), heartbeat task. Ready for services to be plugged in via `asyncio.gather()`.

### Project Config (`pyproject.toml`)
All dependencies declared. Python >=3.12. Ruff + mypy configured. Test config for pytest-asyncio.

---

## What Needs To Be Built (Phases 2–9)

Refer to the implementation plan document for full details. Here's the summary:

### Phase 2 — Market Data & Scanner
- `scanner/universe.py` — Discover penny stocks via Alpaca (primary) or yfinance (fallback), filter by price/market cap, cache in SQLite, refresh daily.
- `data/alpaca_provider.py` — Implement `MarketDataProvider`. WebSocket streaming minute bars via Alpaca free tier (IEX feed). In-memory price cache. REST fallback for sparse tickers.
- `data/polygon_provider.py` — Implement `MarketDataProvider` using Polygon.io Snapshot All Tickers endpoint. Paid fallback.
- `data/yfinance_provider.py` — yfinance for market cap, sector enrichment, asset search, and news.
- `scanner/momentum_scanner.py` — Implement `Scanner`. Detects >X% moves from open/prev close. Cooldown per ticker. Min volume filter. Publishes `MOMENTUM_ALERT`.

### Phase 3 — Sentiment Scraping
- `sentiment/reddit_source.py` — PRAW (sync, wrap with `asyncio.to_thread`). Search penny stock subreddits. Extract posts, scores, author metadata.
- `sentiment/stocktwits_source.py` — REST API. Pre-labelled bullish/bearish. 
- `sentiment/sec_edgar_source.py` — Free API at data.sec.gov. Form 4 (insider trades), 8-K (material events). 10 req/sec, no auth.
- `sentiment/news_source.py` — yfinance + Alpha Vantage news endpoints.
- `sentiment/aggregator.py` — Orchestrates all sources with `asyncio.gather()`. Handles partial failures. Produces `SentimentData`.

### Phase 4 — LLM Analysis Engine
- `analysis/finbert_analyser.py` — HuggingFace `ProsusAI/finbert`. Batch sentiment scoring. Fast preprocessing step.
- `analysis/ollama_analyser.py` — Local Ollama (default: `llama3.2:8b`). Structured JSON output via prompt template from constants.py. 60s timeout.
- `analysis/groq_analyser.py` — Groq SDK. Sub-second. Same prompt.
- `analysis/gemini_analyser.py` — Google Generative AI SDK. Same prompt.
- `analysis/claude_analyser.py` — Anthropic SDK. Same prompt.
- `analysis/report_generator.py` — **Mode 1 (single)**: Sends data to one configured LLM, generates Markdown report.
- `analysis/consensus_generator.py` — **Mode 2 (consensus)**: Sends data to ALL configured LLMs concurrently, collects individual reports, then sends all reports to a meta-analyser LLM (default: Claude) which synthesises agreement/disagreement. Uses `CONSENSUS_META_PROMPT` from constants.py.
- `analysis/fraud_detector.py` — Rule-based + LLM-assisted. Checks: volume spikes, new Reddit accounts, no SEC filings, shell company indicators, sub-penny price, coordinated posting. Outputs `FraudRiskScore`.

### Phase 5 — Trading 212 Broker
- `broker/trading212.py` — Implement `Broker`. HTTP Basic auth (key:secret base64). Endpoints for account summary, positions, market/limit/stop orders, history. **Critical**: API is not idempotent — must deduplicate orders via DB tracking. T212 ticker mapping (e.g. `AAPL` → `AAPL_US_EQ`). Rate limiting per endpoint.
- `broker/paper_broker.py` — Virtual broker for testing. Uses real market data for price sim.

### Phase 6 — Telegram Bot
- `telegram_bot/bot.py` — aiogram 3.x (fully async). BotFather token. Chat ID whitelist.
- `telegram_bot/handlers/alerts.py` — Format and send reports with inline keyboard (BUY/DENY/VIEW REPORT).
- `telegram_bot/handlers/callbacks.py` — Handle button presses. BUY → confirmation → execute. SELL flow.
- `telegram_bot/handlers/positions.py` — `/positions` command. Live P&L. SELL + SET STOP-LOSS buttons. Proactive alerts on thresholds.
- `telegram_bot/handlers/commands.py` — `/start`, `/status`, `/balance`, `/positions`, `/settings`, `/mode`, `/kill`.
- `telegram_bot/formatters.py` — Markdown message formatting.

### Phase 7 — Web Dashboard
- `dashboard/app.py` — FastAPI serving REST API + React static build.
- `dashboard/routes/` — Endpoints for positions, universe, reports, trades, account, orders, stats.
- `dashboard/ws.py` — WebSocket for real-time push (prices, alerts, position changes).
- `dashboard_ui/` — **React 18 + Vite + TailwindCSS**. 7 pages: Dashboard (overview), Universe (all penny stocks), Settings, Reports, Trade History, Account (T212 mirror + order management), Statistics (charts via Recharts).

### Phase 8 — Integration
Wire everything together in `main.py`. The `alert_pipeline` coroutine: receives MOMENTUM_ALERT → scrapes sentiment → assesses fraud → generates report (single or consensus) → saves to DB → pushes to Telegram + dashboard.

### Phase 9 — Testing & Hardening
Unit tests (mock external APIs), integration tests (paper broker), paper trading period (1-2 weeks), circuit breakers, structured logging, health checks, Telegram `/status`.

---

## Key Technical Decisions Already Made

1. **Python 3.12** — All dependencies confirmed compatible. 3.13 works too but 3.12 is the mature sweet spot.

2. **Market data**: Alpaca free tier (IEX feed) as default — provides real-time WebSocket minute bars at zero cost. Polygon.io ($29/mo) as paid fallback. T212 API does NOT provide market prices, only account/position/order data.

3. **Local LLM**: Llama 3.2 8B via Ollama, NOT FinBERT as the primary. FinBERT is retained only as a fast batch sentiment scorer. Research shows Llama 3 outperforms FinBERT on every financial sentiment benchmark.

4. **LLM dual mode**: Mode 1 (single) sends data to one LLM. Mode 2 (consensus) sends to ALL enabled LLMs, then a meta-analyser synthesises. Controlled by `LLM_MODE` env var.

5. **Telegram framework**: aiogram 3.x (not python-telegram-bot) — fully async, native asyncio, no thread pool needed.

6. **Dashboard**: FastAPI backend + React frontend. Dashboard and Telegram bot coexist — dashboard for home use, Telegram for mobile.

7. **Database**: SQLite via aiosqlite. Sufficient for personal use. Easy to migrate to PostgreSQL later if needed (just change the connection string).

8. **T212 API quirks**: Beta, not idempotent (duplicate orders possible), rate limits per endpoint (1 order/2s, 1 summary/5s). Ticker format uses `_US_EQ` suffix. Supports Invest + ISA accounts. Auth is HTTP Basic with key:secret pair.

9. **Fraud detection** feeds into every LLM report as additional context. Not a standalone system — it's an input to the analysis pipeline.

10. **All external integrations are behind abstract interfaces** — swap any provider by implementing the ABC and changing config. Zero coupling between modules.

---

## Implementation Order

```
Phase 2 (scanner) → Phase 5 (broker) → Phase 3 (sentiment) → Phase 4 (LLMs) → Phase 6 (telegram) → Phase 7 (dashboard) → Phase 8 (integration) → Phase 9 (testing)
```

Rationale: Get data flowing and broker connected first (manually testable). Then add intelligence. Then interfaces. Then glue and test.

---

## User Preferences

- Codes in Python. Quant background. BSc financial maths/stats, MSc machine learning.
- Expects clean, typed, well-structured code. Pydantic models, ABC interfaces, async/await.
- Prefers modular architecture where components can be swapped.
- Willing to accept T212 algorithmic trading ToS risk — do not add warnings.
- UK-based, using GBP. Trades US penny stocks via T212 ISA.
- Dashboard + Telegram are complementary, not redundant. Dashboard for home, Telegram for mobile.
