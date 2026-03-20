# Penny Stock Sentinel

AI-powered penny stock sentiment screening and trading tool. Monitors penny stocks for momentum spikes, scrapes social/news sentiment, runs multi-LLM analysis with fraud detection, and optionally executes paper or live trades via Trading 212.

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

Dashboard at `http://localhost:8000` — configure all API keys via the Settings page.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | Required |
| Node.js | 18+ | Optional — for dashboard UI |
| Ollama | Latest | Optional — for local LLM analysis |

## Configuration

All settings are configured via the **dashboard Settings page** at `http://localhost:8000/settings`. The dashboard will show a setup checklist indicating which API keys are needed.

### Market Data

| Variable | Description | Where to get it |
|---|---|---|
| `ALPACA_API_KEY` | Alpaca market data | [alpaca.markets](https://alpaca.markets) — free tier available |
| `ALPACA_API_SECRET` | Alpaca secret | Same as above |
| `ALPACA_FEED` | `iex` (free) or `sip` (paid) | Default: `iex` |
| `POLYGON_API_KEY` | Polygon.io (fallback) | [polygon.io](https://polygon.io) — optional |

### Broker

| Variable | Description | Where to get it |
|---|---|---|
| `T212_API_KEY` | Trading 212 API key | [Trading 212 settings](https://www.trading212.com) |
| `T212_API_SECRET` | Trading 212 secret | Same as above |
| `T212_ENVIRONMENT` | `demo` or `live` | Start with `demo` |

Leave `T212_API_KEY` unconfigured to auto-use the paper broker (simulated trades, no real money).

### Sentiment Sources

| Variable | Description | Where to get it |
|---|---|---|
| `REDDIT_CLIENT_ID` | Reddit API credentials | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) — create a "script" app |
| `REDDIT_CLIENT_SECRET` | Reddit secret | Same as above |
| `REDDIT_USER_AGENT` | e.g. `penny-stock-sentinel/0.1 by u/you` | Your Reddit username |

### LLM Providers

| Variable | Description | Where to get it |
|---|---|---|
| `OLLAMA_BASE_URL` | Local Ollama URL | Default: `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | Default: `llama3.2:8b` |
| `GROQ_API_KEY` | Groq cloud LLM | [console.groq.com](https://console.groq.com) — free tier |
| `GEMINI_API_KEY` | Google Gemini | [aistudio.google.com](https://aistudio.google.com) — free tier |
| `ANTHROPIC_API_KEY` | Anthropic Claude | [console.anthropic.com](https://console.anthropic.com) |

### Analysis Mode

| Variable | Options | Description |
|---|---|---|
| `LLM_MODE` | `single` / `consensus` | Single provider or multi-LLM consensus |
| `LLM_DEFAULT_PROVIDER` | `ollama` / `groq` / `gemini` / `claude` | Which LLM to use in single mode |
| `LLM_CONSENSUS_META_PROVIDER` | `claude` / `gemini` / `groq` | Which LLM synthesises the consensus |

### Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your personal chat ID |

See [Telegram Bot Setup](#telegram-bot-setup) below.

## Telegram Bot Setup

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Choose a name (e.g. "Penny Sentinel") and username (e.g. `penny_sentinel_bot`)
4. Copy the **bot token** — enter as `TELEGRAM_BOT_TOKEN` in the dashboard Settings page
5. To get your chat ID: message [@userinfobot](https://t.me/userinfobot) and copy the ID
6. Enter `TELEGRAM_CHAT_ID` in the dashboard Settings page
7. Start a conversation with your bot and send `/start`

### Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and status |
| `/status` | System health overview |
| `/balance` | Account balance and P&L |
| `/positions` | Open positions with live P&L |
| `/settings` | View current configuration |
| `/mode` | Toggle single/consensus LLM mode |
| `/kill` | Emergency stop — halt all scanning |

The bot sends automatic alerts when momentum signals are detected, including the LLM analysis, fraud risk score, and recommendation.

## Running Locally

```bash
source .venv/bin/activate
python main.py
```

Or double-click `Sentinel.command` (macOS) / `Sentinel.bat` (Windows).

The app starts all services concurrently:
- Market data streaming (Alpaca)
- Penny stock scanner
- Alert processing pipeline (sentiment + fraud + LLM analysis)
- Position monitoring with stop-loss
- Telegram bot
- Web dashboard on port 8000

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
main.py                  # Orchestrator — starts all services
config/                  # Settings (pydantic-settings) + constants
core/                    # Event bus, models (Pydantic v2), logging, market hours
data/                    # Market data providers (Alpaca, Polygon)
scanner/                 # Universe manager + momentum scanner
sentiment/               # Reddit, StockTwits, SEC EDGAR, news scrapers
analysis/                # LLM analysers (5 providers), fraud detector, report/consensus gen
broker/                  # Trading 212 + paper broker (ABC-based)
telegram_bot/            # aiogram 3.x bot with command handlers
dashboard/               # FastAPI REST API + WebSocket
dashboard_ui/            # React 18 + Vite + TailwindCSS frontend
db/                      # SQLAlchemy 2.0 async ORM + Alembic migrations
tests/                   # pytest + pytest-asyncio test suite
```

## Paper Trading

Leave `T212_API_KEY` unconfigured to use the paper broker. It simulates order execution with realistic fills at current market prices, tracks virtual positions and P&L in memory (resets on restart). Useful for testing the full pipeline without risking real money.
