# Florin Terminal

AI-powered financial terminal for market screening, multi-LLM analysis, portfolio management, and trading. Supports equities, ETFs, indices, mutual funds, and cryptocurrencies across 20+ global exchanges.

## Quick Start

```bash
./setup.sh        # macOS/Linux
# or
setup.bat         # Windows
```

```bash
source .venv/bin/activate
python main.py
```

Dashboard at `http://localhost:8000` — configure API keys via the Settings page.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | Required |
| Node.js | 18+ | Required for dashboard UI |

## Features

### Research
- **Asset search** across equities, ETFs, indices, mutual funds, and crypto
- **Cumulative return charts** with comparison overlays (up to 4 tickers)
- **Intraday and daily** data with configurable period selection (1min–monthly)
- **Options chain** viewer with Greeks (delta, gamma, theta, vega)
- **Regime detection** via Markov switching regression (2 or 3 regimes, self or benchmark-driven)
- **Returns histogram** and distribution analysis
- **Risk metrics** — Sharpe ratio, max drawdown, annualised volatility, VaR, CVaR
- **Short interest** tracking
- **Insider activity** monitoring
- **Top institutional holders** (13F filings)
- **LLM-powered analysis** — single or multi-LLM consensus mode with 4 provider options

### Screening
- **Multi-asset screener** — stocks, ETFs, indices, mutual funds, crypto
- **20+ regions** — US, UK, Germany, Japan, Hong Kong, Australia, and more
- **Per-region exchange filtering** (NYSE, NASDAQ, LSE, TSE, HKEX, etc.)
- **OTC markets** with individual tier selection (Pink Sheets, OTCQB, OTCQX)
- **ADR detection** and filtering
- **Momentum, price, volume, and market cap filters**
- **Save and manage** screener configurations
- **Telegram alerts** on screener matches

### Monitoring
- **Watchlist** with custom notes and targets
- **Live monitor** with 30-second polling and sparkline charts
- **Price alerts**

### Trading
- **Paper broker** (default) — simulated trading with virtual capital
- **Trading 212** integration — live or demo accounts
- **Order management** — market, limit, and stop-loss orders
- **Position monitoring** with automatic stop-loss enforcement
- **Trade history** and performance statistics (win rate, Sharpe, P&L charts)

### Portfolio Management
- **Custom portfolios** with weighted holdings
- **Portfolio analytics** — correlation matrix, risk decomposition, regime analysis
- **Returns analysis** with benchmark comparison
- **Copula-based** dependency modelling

### Market Intelligence
- **Market breadth** scanner (advance/decline, new highs/lows)
- **Economic calendar**
- **News feed** with sentiment aggregation
- **Cross-asset correlation** matrices (including global indices, commodities, FX)
- **Yield curve** viewer with historical comparison
- **G10 risk-free rates** from central banks

### Alerts & Notifications
- **Telegram bot** — mobile alerts, trading commands, portfolio monitoring
- **Screener alerts** — automatic notifications when scan criteria are met
- **Multi-LLM reports** attached to alerts with fraud risk assessment

## Configuration

All settings are configured via the **dashboard Settings page** at `http://localhost:8000/settings`, or through environment variables / `.env` file.

### Market Data

| Variable | Description | Where to get it |
|---|---|---|
| `ALPACA_API_KEY` | Alpaca real-time market data | [alpaca.markets](https://alpaca.markets) — free tier available |
| `ALPACA_API_SECRET` | Alpaca secret | Same as above |
| `ALPACA_FEED` | `iex` (free) or `sip` (paid) | Default: `iex` |

yfinance is used automatically for historical data, asset info, screening, and enrichment — no API key required.

### Broker

| Variable | Description | Where to get it |
|---|---|---|
| `T212_API_KEY` | Trading 212 API key | [Trading 212 settings](https://www.trading212.com) |
| `T212_API_SECRET` | Trading 212 secret | Same as above |
| `T212_ENVIRONMENT` | `demo` or `live` | Start with `demo` |

Leave `T212_API_KEY` unconfigured to use the **paper broker** (simulated trades, no real money).

### Sentiment Sources

| Variable | Description | Where to get it |
|---|---|---|
| `REDDIT_CLIENT_ID` | Reddit API credentials | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) — create a "script" app |
| `REDDIT_CLIENT_SECRET` | Reddit secret | Same as above |
| `REDDIT_USER_AGENT` | e.g. `florin-terminal/0.2 by u/you` | Your Reddit username |

### LLM Providers

| Variable | Description | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | Groq cloud LLM API key | [console.groq.com](https://console.groq.com) — free tier |
| `GEMINI_API_KEY` | Google Gemini API key | [aistudio.google.com](https://aistudio.google.com) — free tier |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key (optional — CLI auth supported) | [console.anthropic.com](https://console.anthropic.com) or `claude login` |

> **Anthropic CLI:** Claude uses the [Claude Code CLI](https://github.com/anthropics/claude-agent-sdk-python) (`claude-agent-sdk`). Install the CLI with `npm install -g @anthropic-ai/claude-code`, then authenticate with `claude login` (Pro/Max subscribers). An API key is optional — if omitted, CLI session auth is used. Configurable thinking modes: off, low, medium, high, max.

### Analysis Mode

| Variable | Options | Description |
|---|---|---|
| `LLM_MODE` | `single` / `consensus` | Single provider or multi-LLM consensus |
| `LLM_DEFAULT_PROVIDER` | `groq` / `gemini` / `claude-cli` / `openrouter` | Which LLM to use in single mode |
| `LLM_CONSENSUS_META_PROVIDER` | `claude-cli` / `gemini` / `groq` / `openrouter` | Which LLM synthesises the consensus |

### Trading

| Variable | Default | Description |
|---|---|---|
| `PAPER_TRADING` | `true` | Must explicitly set `false` for live trading |
| `DEFAULT_POSITION_SIZE` | `100.0` | Position size in configured currency |
| `POSITION_SIZE_UNIT` | `gbp` | `gbp`, `usd`, or `shares` |
| `DEFAULT_STOP_LOSS_PCT` | `10.0` | Stop-loss threshold (%) |
| `MAX_OPEN_POSITIONS` | `10` | Maximum concurrent positions |

### Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your personal chat ID |

See [Telegram Bot Setup](#telegram-bot-setup) below.

## Telegram Bot Setup

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Choose a name (e.g. "Florin Terminal") and username (e.g. `florin_terminal_bot`)
4. Copy the **bot token** — enter as `TELEGRAM_BOT_TOKEN` in the dashboard Settings page
5. To get your chat ID: message [@userinfobot](https://t.me/userinfobot) and copy the ID
6. Enter `TELEGRAM_CHAT_ID` in the dashboard Settings page
7. Start a conversation with your bot and send `/start`

### Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and command help |
| `/status` | System health overview |
| `/balance` | Account balance and P&L |
| `/positions` | Open positions with live P&L |
| `/settings` | View current configuration |
| `/mode` | Current LLM mode (single/consensus) |
| `/kill` | Emergency stop — cancel all pending orders |
| `/buy TICKER [size]` | Place buy order (e.g. `/buy AAPL £50`) |

The bot sends automatic alerts when screener matches are found or momentum signals are detected, including LLM analysis, fraud risk score, and recommendation with interactive BUY/PASS buttons.

## Running Locally

```bash
source .venv/bin/activate
python main.py
```

Or double-click `Florin.command` (macOS) / `Florin.bat` (Windows).

The app starts all services concurrently:
- Market data providers (Alpaca real-time + yfinance historical)
- Screener alert service with saved configurations
- Alert processing pipeline (sentiment + LLM analysis)
- Position monitoring with stop-loss enforcement
- Market breadth scanner
- Telegram bot (if configured)
- Web dashboard on port 8000
- WebSocket event bridge for real-time updates

## Running with Docker

```bash
docker compose up -d
```

Dashboard at `http://your-server:8000`. Configure API keys via the Settings page.

## Dashboard Dev Mode

For frontend development with hot reload:

```bash
# Terminal 1: backend
source .venv/bin/activate && python main.py

# Terminal 2: frontend (proxies API to backend)
cd dashboard_ui && npm run dev
```

Frontend dev server at `http://localhost:5173`, proxying API calls to port 8000.

## Architecture

```
main.py                  # Florin orchestrator — starts all services
config/                  # Settings (pydantic-settings) + constants
core/                    # Event bus, Pydantic models, logging, market hours
data/                    # Market data providers (Alpaca, yfinance)
scanner/                 # Screener alert service + market breadth scanner
sentiment/               # Reddit, StockTwits, SEC EDGAR, news scrapers
analysis/                # LLM analysers (5 providers), fraud detector, report generators
broker/                  # Trading 212 + paper broker (ABC-based)
telegram_bot/            # aiogram 3.x bot with command handlers
stats/                   # Statistical models (regime detection, risk metrics)
dashboard/               # FastAPI REST API (25 route modules) + WebSocket
dashboard_ui/            # React 19 + Vite 8 + TailwindCSS 4 frontend
db/                      # SQLAlchemy 2.0 async ORM + Alembic migrations
tests/                   # pytest + pytest-asyncio test suite (600+ tests)
```

### Navigation Structure

| Tab | Path | Description |
|---|---|---|
| Research | `/` | Asset search, detailed analysis with sub-tabs (Overview, Quantitative, Options, Holders, Broker) |
| Monitoring | `/monitoring` | Watchlist management + live price monitor |
| Screener | `/screener` | Multi-asset screener with saved configurations |
| 13F Filings | `/13f` | Institutional holdings search (SEC EDGAR) |
| News | `/news` | Market news feed |
| Calendar | `/calendar` | Economic calendar |
| Reports | `/reports` | Generated LLM analysis reports |
| Portfolio | `/portfolio` | Custom portfolio management + analytics |
| Data | `/data` | Historical data download |
| Trading | `/trading` | Trading dashboard, account, trades, stats, screener configs, settings |
| Settings | `/settings` | System configuration (gear icon) |

### API Documentation

Interactive API docs are available at `http://localhost:8000/api/docs` (Swagger UI) once the server is running. The API exposes 80+ endpoints across 25 route modules.

## Paper Trading

Leave `T212_API_KEY` unconfigured to use the paper broker. It simulates order execution with realistic fills at current market prices, tracks virtual positions and P&L in memory (resets on restart). The paper broker starts with £10,000 virtual capital and enforces the same position limits and stop-loss rules as live trading.

## Technology Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), SQLite (WAL mode), Alembic
- **Frontend:** React 19, Vite 8, TailwindCSS 4, React Router 7, Recharts
- **Real-time:** WebSocket at `/ws`, async EventBus pub/sub
- **LLM:** Groq, Gemini, Claude CLI, OpenRouter (cloud)
- **Statistical:** statsmodels (Markov regime switching), copulax (copula modelling)
- **Telegram:** aiogram 3.x (fully async)
