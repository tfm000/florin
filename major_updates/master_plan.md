# Florin Major Update — Master Plan

## Overview

This plan covers a 10-phase transformation of "Penny Stock Sentinel" into "Florin" — a general-purpose financial terminal.

## Before Starting Any Phase

1. Read and follow `agent.md` — it defines strict quality standards for this project.
2. Check this file to see which phases are complete and which is next.
3. Read the specific phase plan file before implementing.
4. Use the project venv for all Python operations.
5. Rebuild frontend (`cd dashboard_ui && npm run build`) after any frontend changes.
6. Run tests (`python -m pytest tests/`) after every phase.

## Execution Order

| # | Plan File | Phase | Status | Dependencies |
|---|-----------|-------|--------|--------------|
| 1 | `01_codebase_audit.md` | Codebase audit, deduplication, testing, DB/cache review | **COMPLETE** | None |
| 2 | `02_spa_routing_fix.md` | Fix SPA page reload crash | **COMPLETE** | None |
| 3 | `03_research_improvements.md` | Correlation matrices, sector chart enhancements | **COMPLETE** | Phase 2 |
| 4 | `04_monitoring_consolidation.md` | Merge Watchlist + Live Monitor into "Monitoring" tab | Not started | Phase 2 |
| 5 | `05_trading_consolidation.md` | Merge Dashboard/Account/Trades/Stats under "Trading" tab | Not started | Phase 4 |
| 6 | `06_screener_redesign.md` | Enhanced screener with momentum, volume, save functionality | Not started | Phase 5 |
| 7 | `07_live_alerts.md` | Screener-based Telegram alerts with optional LLM reports | Not started | Phase 6 |
| 8 | `08_rename_to_florin.md` | Rebrand: Sentinel → Florin, new logos, remove penny-stock refs | Not started | Phase 7 |
| 9 | `09_final_audit.md` | Second codebase audit post-changes | Not started | Phase 8 |
| 10 | `10_documentation.md` | Update all docs, READMEs, installation instructions | Not started | Phase 9 |
| - | `math_errors.md` | Document math/stats fragilities (created during Phase 1) | Not started | Phase 1 |

## Key Design Decisions (confirmed by user)

1. **Cross-asset correlation tickers**: Use direct index tickers (`^FTSE`, `^GDAXI`, `GC=F`, `CL=F`, `NG=F`) rather than US-listed ETF proxies.
2. **Settings architecture**: Move Trading/Broker/Telegram settings into Trading tab. Remove Scanner settings entirely (replaced by Trade Screener configs). Keep remaining settings (Market Data, Sentiment, LLM, Analysis, General) in a standalone page accessed via a **gear icon** in the navbar (not a tab).
3. **Audit approach**: Break Phase 1 into sub-phases by module group, each with its own commit.
4. **Scanner fate**: The old penny-stock momentum scanner and universe manager will be **fully replaced** by the new screener alert service in Phase 7. Remove the old scanner infrastructure entirely.
5. **Remove Polygon provider**: Delete `data/polygon_provider.py` and all references. The project uses Alpaca and yfinance for market data.

## Project Architecture

- **Backend:** FastAPI (Python 3.12+), SQLAlchemy async + SQLite (WAL mode), Alembic migrations
- **Frontend:** React 19, Vite 8, TailwindCSS 4, React Router 7, Recharts
- **Real-time:** WebSocket at `/ws`, EventBus pub/sub internally
- **Entry point:** `main.py` → `Sentinel` class (to become `Florin`)
- **Static serving:** `dashboard/app.py` mounts `dashboard/static/` at `/`
- **Tests:** 34 test files in `tests/`, pytest + pytest-asyncio

## Key File Locations

- App factory: `dashboard/app.py`
- Frontend routes: `dashboard_ui/src/App.jsx`
- DB models: `db/models.py`
- Settings: `config/settings.py`
- API routes: `dashboard/routes/*.py`
- Main orchestrator: `main.py`
- Telegram bot: `telegram_bot/`
- Statistical code: `stats/`
- Scanner: `scanner/`
- New logos: `florin_light.PNG`, `florin_dark.PNG` (project root)

## Rules

- **No mathematical/statistical code changes** without explicit approval. Document issues in `math_errors.md` instead.
- **No partial implementations.** Every file touched must be complete.
- **No silent failures.** Report all errors encountered.
- **Full testing** for every user-facing module and API.
- **Run Alembic migrations** for any DB model changes.
