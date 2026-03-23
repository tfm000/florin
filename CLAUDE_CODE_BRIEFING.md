# CLAUDE_CODE_BRIEFING.md

## What This Project Is

**Florin Terminal** is an AI-powered financial terminal for market screening, multi-LLM analysis, portfolio management, and trading. It supports equities, ETFs, indices, mutual funds, and cryptocurrencies across 20+ global exchanges. The web dashboard provides research, monitoring, screening, and trading capabilities. A Telegram bot provides mobile alerts and trade execution.

The user trades via a **Trading 212 Stocks and Shares ISA** and is aware that T212's terms prohibit algorithmic trading — they accept this risk. Do not second-guess this decision or add warnings about it.

---

## Architecture

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), SQLite (WAL mode), Alembic migrations
- **Frontend:** React 19, Vite 8, TailwindCSS 4, React Router 7, Recharts
- **Real-time:** WebSocket at `/ws`, async EventBus pub/sub
- **Entry point:** `main.py` → `Florin` orchestrator class
- **Static serving:** `dashboard/app.py` mounts `dashboard/static/` at `/`
- **Tests:** 600+ tests in `tests/`, pytest + pytest-asyncio

### Key File Locations

| Area | Path |
|------|------|
| App factory | `dashboard/app.py` |
| Frontend routes | `dashboard_ui/src/App.jsx` |
| DB models | `db/models.py` |
| Settings | `config/settings.py` |
| API routes | `dashboard/routes/*.py` (25 modules) |
| Main orchestrator | `main.py` |
| Telegram bot | `telegram_bot/` |
| Statistical code | `stats/` |
| Screener engine | `dashboard/services/screener_engine.py` |
| Chart colors | `dashboard_ui/src/hooks/useChartColors.jsx` |
| Quality standards | `agent.md` |

### Services (started by `main.py`)

1. **Heartbeat** — periodic health check logs
2. **Risk-Free Rate Refresh** — daily G10 rates from central banks
3. **Screener Alert Service** — runs saved screener configurations on interval
4. **Alert Pipeline** — sentiment → fraud → LLM analysis → DB → Telegram
5. **Position Monitor** — polls broker, enforces stop-losses
6. **Telegram Bot** — command handlers + alert listeners
7. **Dashboard Server** — FastAPI + React SPA
8. **Market Breadth Scanner** — hourly advance/decline scans
9. **WebSocket Event Bridge** — pushes events to connected clients

### Market Data

- **Alpaca** — real-time quotes via WebSocket (IEX free tier)
- **yfinance** — historical data, asset info, screening, enrichment (no API key needed)

### LLM Providers

FinBERT (local batch sentiment), Ollama (local general), Groq (cloud), Gemini (cloud), Claude (cloud). Supports single-provider or multi-LLM consensus mode.

---

## Key Technical Decisions

1. **No Polygon provider** — removed. Uses Alpaca + yfinance for all market data.
2. **Screener uses yfinance** — `EquityQuery` for stocks, `FundQuery` for funds, direct Yahoo POST for ETFs/indices/crypto.
3. **ADR detection** — `financialCurrency != currency` from Yahoo data.
4. **OTC markets** — Yahoo uses `PNK` for all OTC tiers (includes large-cap ADRs alongside penny stocks).
5. **Colorblind-safe palette** — blue/red (not blue/orange), managed by `useChartColors()` context hook.
6. **Regime detection** — Markov switching regression via statsmodels, supports intraday and daily frequencies with appropriate annualisation factors.
7. **Intraday data** — `INTRADAY_TO_HISTORY` mapping in `PeriodSelector.jsx` translates UI keys to yfinance period+interval pairs.
8. **Database** — SQLite via aiosqlite. Auto-migrates `sentinel.db` → `florin.db` on startup.
9. **Paper trading** — default mode. Must explicitly set `PAPER_TRADING=false` for live.
10. **All external integrations behind abstract interfaces** — swap any provider by implementing the ABC.

---

## Quality Standards

See `agent.md` for the full quality bar. Key rules:

- **No mathematical/statistical code changes** without explicit approval
- **No partial implementations** — every file touched must be complete
- **No silent failures** — report all errors
- **Full testing** for every user-facing module and API
- **Run Alembic migrations** for any DB model changes
- **Rebuild frontend** after any frontend edits (`cd dashboard_ui && npm run build`)

---

## User Preferences

- Codes in Python. Quant background. BSc financial maths/stats, MSc machine learning.
- Expects clean, typed, well-structured code. Pydantic models, ABC interfaces, async/await.
- Prefers modular architecture where components can be swapped.
- UK-based, using GBP. Trades US equities via T212 ISA.
- Dashboard for home use, Telegram for mobile.
