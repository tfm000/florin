# Sentinel Terminal: Bloomberg Terminal Clone Transformation

## Context
The project is being transformed from a penny-stock-only sentinel into a multi-asset Bloomberg terminal clone. The penny stock feature set remains as a dedicated module, but the platform now supports research across all asset classes (equities, fixed income, crypto, derivatives) via yfinance.

**Previous work** (from prior session) is ~80% done: settings updates (price min/max, market cap, position size unit, LLM user context), Alpaca universe discovery, health endpoint, frontend settings textarea, and StockTable market cap column are all implemented. What remains: fix broken tests, then proceed with the transformation.

**Key changes:**
1. Fix existing tests, finish previous task
2. Remove FMP entirely — replace with yfinance for market cap/enrichment/news
3. Add Research tab (asset search, Bloomberg RSS, yield curves, G10 rates) with per-asset research sub-pages including LLM analysis
4. Add Watchlist and Live Monitor tabs
5. Reorganise penny stocks: yfinance for initial filtering, Alpaca for live monitoring, ranked by today's return
6. Rebrand UI as "Sentinel Terminal"
7. Enhance Telegram bot with richer alert messages and order size specification
8. Dual market cap sources: yfinance market cap + Alpaca-inferred (shares × price), user selects which to use for scanning

---

## Phase 0: Fix Tests & Stabilise

**Goal:** Get existing tests passing after the previous session's changes.

### Broken tests to fix

**`tests/test_config.py`** (lines 108-120):
- References `scan_price_threshold` which was renamed to `scan_price_max`
- Change `scan_price_threshold=5.0` → `scan_price_max=5.0` and assertion accordingly

**`tests/test_scanner.py`** (lines 26-31):
- `_make_universe()` passes `fmp_api_key="test"` and `scan_price_threshold=5.0` — both removed/renamed
- Remove `fmp_api_key` param, change `scan_price_threshold` → `scan_price_max`

**`tests/test_dashboard.py`**:
- Verify health endpoint expectations match new checklist (FMP is now optional, not required)

**`tests/test_sentiment.py`**:
- May reference FMP news mocks — defer full fix to Phase 1

### Actions
1. Fix the test files above
2. Run `pytest tests/ -x -q`
3. Fix any additional failures

---

## Phase 1: Remove FMP, Add yfinance

**Goal:** Completely eliminate FMP from the codebase. yfinance replaces it for enrichment, news, and asset data. No FMP references should remain in code or documentation.

### 1a. Add yfinance dependency
- **MODIFY** `pyproject.toml` — add `"yfinance>=0.2.36"`
- Run `pip install -e .`

### 1b. Create yfinance provider
- **CREATE** `data/yfinance_provider.py`

```python
class YFinanceProvider:
    """Asset data via Yahoo Finance. Powers research, enrichment, and penny stock screening."""

    async def search(self, query: str) -> list[dict]:
        """Search tickers by name/symbol."""

    async def get_info(self, ticker: str) -> dict:
        """Full asset info: name, sector, industry, market_cap, pe_ratio, short_interest, exchange, shares_outstanding."""

    async def get_history(self, ticker: str, period="1y", interval="1d") -> list[dict]:
        """Historical OHLCV data."""

    async def get_performance_metrics(self, ticker: str) -> dict:
        """Sharpe, max drawdown, 1M/6M/1Y/3Y returns from history."""

    async def get_news(self, ticker: str) -> list[dict]:
        """Recent news via yf.Ticker(ticker).news."""

    async def enrich_batch(self, tickers: list[str], max_calls=50) -> dict[str, dict]:
        """Batch enrichment: market_cap, sector, industry, shares_outstanding. Rate-limited."""

    async def filter_penny_stocks(self, price_min, price_max, market_cap_min=0, market_cap_max=0) -> list[StockInfo]:
        """Screen for penny stocks using yfinance screener module. No return-based filtering."""

    async def get_yield_curve(self, region="US") -> dict:
        """Treasury yields for curve construction. US: ^IRX, ^FVX, ^TNX, ^TYX, etc."""

    async def get_g10_rates(self) -> list[dict]:
        """G10 central bank policy rates (semi-static, updated on decisions)."""

    async def get_macro_summary(self) -> dict:
        """Macro economic indicators for LLM context (VIX, DXY, key indices, oil, gold)."""
```

All yfinance calls wrapped in `asyncio.to_thread()` (yfinance is synchronous). Add TTL cache (5 min for info, 1 hour for history).

### 1c. Delete FMP provider
- **DELETE** `data/fmp_provider.py`

### 1d. Update all FMP references — every single one removed

| File | Change |
|------|--------|
| `config/settings.py` | Remove `fmp_api_key: str = ""` |
| `dashboard/routes/settings.py` | Remove `fmp_api_key` from `_SECRET_KEYS` and `market_data` section keys |
| `dashboard/routes/health.py` | Remove FMP checklist item, remove `fmp_configured` from response |
| `scanner/universe.py` | Replace `FMPProvider` import/usage with `YFinanceProvider`. Replace `_enrich_from_fmp()` with `_enrich_from_yfinance()`. Remove FMP fallback in `refresh()` |
| `sentiment/news_source.py` | Replace FMP news with yfinance news (`yf.Ticker(ticker).news`). Remove `FMP_NEWS_URL`, `_fetch_fmp_news()`, `_parse_fmp_article()`. Remove `self._fmp_key`. Keep Alpha Vantage as supplementary |
| `main.py` | Remove FMP warning. Instantiate `YFinanceProvider`, pass to `set_state("yfinance_provider", ...)` |
| `dashboard/deps.py` | Add `get_yfinance_provider()` accessor |
| `data/base.py` | Remove FMP from docstring |
| `config/constants.py` | Remove any FMP comments |
| `README.md` | Remove all FMP references |
| `CLAUDE_CODE_BRIEFING.md` | Remove all FMP references |

### 1e. Market cap: dual source support
- **yfinance market cap**: from `yf.Ticker(ticker).info["marketCap"]`
- **Alpaca-inferred market cap**: `shares_outstanding × current_price` (shares_outstanding from yfinance `get_info()`)
- Both values stored on `StockInfo` model: add `shares_outstanding: int | None = None` and `inferred_market_cap: float | None = None` fields to `core/models.py`
- Add setting `market_cap_source: str = "yfinance"` (choices: `["yfinance", "inferred"]`) to `config/settings.py`
- Dashboard displays both in the penny stock table
- Scanner uses the user-selected source for market cap filtering
- Add `market_cap_source` to `dashboard/routes/settings.py` scanner section with choices

### 1f. Update tests
- **MODIFY** `tests/test_scanner.py` — remove `fmp_api_key` references, mock yfinance where needed
- **MODIFY** `tests/test_sentiment.py` — replace FMP news mocks with yfinance news mocks
- **MODIFY** `tests/test_dashboard.py` — update health check: no FMP in checklist
- **CREATE** `tests/test_yfinance_provider.py` — test search, info, history, enrichment, performance metrics

---

## Phase 2: Database Models for New Features

**Goal:** Add tables for watchlist and monitored assets.

### 2a. New ORM models in `db/models.py`

```python
class WatchlistORM(Base):
    __tablename__ = "watchlist"
    id: str (PK, auto-generated)
    ticker: str (indexed, unique)
    name: str
    asset_type: str  # "equity", "crypto", "etf", "bond", "index"
    notes: str (Text)
    added_at: datetime

class MonitoredAssetORM(Base):
    __tablename__ = "monitored_assets"
    id: str (PK, auto-generated)
    ticker: str (indexed, unique)
    name: str
    source: str  # "alpaca", "manual"
    asset_type: str
    is_active: bool (default True)
    added_at: datetime
```

### 2b. Add new event types in `core/events.py`
- `PRICE_UPDATE = "price_update"`
- `MONITOR_UPDATE = "monitor_update"`

---

## Phase 3: Backend API Routes

**Goal:** New REST endpoints for Research, Watchlist, Live Monitor.

### 3a. Research endpoints
- **CREATE** `dashboard/routes/research.py`

```
GET /api/research/search?q=AAPL              → yfinance search results
GET /api/research/asset/{ticker}              → full asset info + performance metrics
GET /api/research/asset/{ticker}/history      → historical prices (query: period, interval)
GET /api/research/asset/{ticker}/analyse      → LLM analysis report for any asset (see 3a.1)
GET /api/research/news                        → Bloomberg Markets RSS (parsed server-side)
GET /api/research/yield-curve?region=US       → yield curve data points
GET /api/research/policy-rates                → G10 central bank rates
```

**3a.1 — LLM Analysis for any asset (`/analyse` endpoint)**

Generates an LLM report on any searched asset, not just penny stocks. Uses the same analysis pipeline (ReportGenerator/ConsensusGenerator) but with an enriched prompt that includes:
- **Macro context**: VIX, DXY, key index levels, recent Bloomberg headlines (from `YFinanceProvider.get_macro_summary()`)
- **Asset-specific news**: recent headlines from yfinance (`yf.Ticker(ticker).news`)
- **Performance metrics**: Sharpe, drawdown, period returns (from `get_performance_metrics()`)
- **Fundamentals**: PE, market cap, short interest, sector

Implementation:
- Add `RESEARCH_ANALYSIS_PROMPT` to `config/constants.py` — similar to `SINGLE_REPORT_PROMPT` but with macro + news sections and without the penny-stock-specific fraud/volume analysis
- Add `build_research_prompt()` to `analysis/_prompt_helper.py` — builds prompt from yfinance data + macro context
- The `/analyse` endpoint constructs an `AlertSignal`-like object from yfinance data, builds a `SentimentData` from yfinance news, creates a minimal `FraudRiskScore`, and runs through the existing analyser pipeline
- Returns the same `LLMAnalysis` structure for the frontend to render

Bloomberg RSS: `https://feeds.bloomberg.com/markets/news.rss` — fetch and parse XML server-side. Fallback to Yahoo Finance RSS if unavailable.

Yield curves:
- US: `^IRX` (3M), `^FVX` (5Y), `^TNX` (10Y), `^TYX` (30Y), plus 2Y
- UK, Japan, Europe: bond ETF proxies initially

G10 rates: semi-static dict with rate, central bank name, last decision date.

### 3b. Watchlist endpoints
- **CREATE** `dashboard/routes/watchlist.py`

```
GET    /api/watchlist              → list all watched assets
POST   /api/watchlist              → add {ticker, notes?}
DELETE /api/watchlist/{ticker}     → remove
PUT    /api/watchlist/{ticker}     → update notes
```

### 3c. Live Monitor endpoints
- **CREATE** `dashboard/routes/monitor.py`

```
GET    /api/monitor                → list monitored assets with latest prices
POST   /api/monitor                → add {ticker} for live monitoring
DELETE /api/monitor/{ticker}       → stop monitoring
```

When added, subscribe ticker to Alpaca WebSocket via `data_provider.update_subscriptions()`.

### 3d. Register routes
- **MODIFY** `dashboard/app.py` — include research, watchlist, monitor routers. Rename title to "Sentinel Terminal"
- **MODIFY** `dashboard/deps.py` — add `get_yfinance_provider()`
- **MODIFY** `dashboard/ws.py` — add PRICE_UPDATE and MONITOR_UPDATE to event bridge channels

### 3e. Update universe API
- **MODIFY** `dashboard/routes/universe.py` — add `today_return`, `is_monitored`, `shares_outstanding`, `inferred_market_cap` fields to response. Add `sort_by=today_return` option.

### 3f. Tests
- **CREATE** `tests/test_research.py`, `tests/test_watchlist.py`, `tests/test_monitor.py`

---

## Phase 4: Frontend — New Pages & Navigation

**Goal:** Add Research, Watchlist, Live Monitor pages. Restructure nav.

### 4a. Navigation restructure
- **MODIFY** `dashboard_ui/src/App.jsx`

```javascript
NAV_ITEMS = [
  { path: '/', label: 'Dashboard' },
  { path: '/research', label: 'Research' },
  { path: '/watchlist', label: 'Watchlist' },
  { path: '/monitor', label: 'Live Monitor' },
  { path: '/penny-stocks', label: 'Penny Stocks' },  // renamed from /universe
  { path: '/reports', label: 'Reports' },
  { path: '/trades', label: 'Trades' },
  { path: '/account', label: 'Account' },
  { path: '/stats', label: 'Stats' },
  { path: '/settings', label: 'Settings' },
]
```

Add route: `/research/:ticker` → AssetResearch sub-page.
Rebrand nav title: "Sentinel" → "Sentinel Terminal".

### 4b. Research main page
- **CREATE** `dashboard_ui/src/pages/Research.jsx`
- Search bar at top (debounced, dropdown results, click → `/research/:ticker`)
- Bloomberg News feed (scrollable headline cards)
- Yield Curve chart (Recharts LineChart, region dropdown: US/UK/Japan/Europe)
- G10 Policy Rates table

### 4c. Asset Research sub-page
- **CREATE** `dashboard_ui/src/pages/AssetResearch.jsx`
- Header: ticker, name, exchange, sector
- Key metrics grid: market cap, PE, short interest, Sharpe, max drawdown, 1M/6M/1Y/3Y returns
- Cumulative return chart (Recharts): period selector (1M/3M/6M/1Y/3Y/MAX), overlay selector to add comparison assets
- Action buttons:
  - **Watch** → POST /api/watchlist (toggles if already watching)
  - **Live Monitor** → POST /api/monitor (Alpaca-supported assets only)
  - **LLM Analyse** → POST /api/research/asset/{ticker}/analyse — generates a full LLM report with macro context + news headlines. Shows loading spinner, then renders report inline using existing ReportViewer component pattern
  - **BUY / SELL** → order modal using existing TradeForm pattern (only for T212-supported instruments)

### 4d. Watchlist page
- **CREATE** `dashboard_ui/src/pages/Watchlist.jsx`
- Table: ticker, name, last price, today's change, market cap, added date, notes
- Each row clickable → `/research/:ticker`
- Remove button per row

### 4e. Live Monitor page
- **CREATE** `dashboard_ui/src/pages/LiveMonitor.jsx`
- Table with WebSocket-fed real-time prices
- Columns: ticker, name, price, change %, volume, status indicator (green/yellow/red dot)
- Remove button, row click → `/research/:ticker`

### 4f. Rename Universe → Penny Stocks
- **MODIFY** `dashboard_ui/src/pages/Universe.jsx`
- Rename heading
- Add columns: today's return (sorted desc by default), live monitored status, shares outstanding, inferred market cap
- Each row links to `/research/:ticker`
- Show both yfinance market cap and inferred market cap columns

### 4g. New shared components
- **CREATE** `dashboard_ui/src/components/SearchBar.jsx` — debounced search input with dropdown
- **CREATE** `dashboard_ui/src/components/CumulativeReturnChart.jsx` — Recharts LineChart with period selector + overlay
- **CREATE** `dashboard_ui/src/components/YieldCurveChart.jsx` — Recharts LineChart for yield curves
- **CREATE** `dashboard_ui/src/components/NewsCard.jsx` — single news story card

---

## Phase 5: Penny Stock Pipeline Reorganisation

**Goal:** yfinance for initial filtering (no return-based filtering), Alpaca for live monitoring.

### Flow
1. **yfinance** screens for penny stocks: price range + market cap + exchange filters only (no returns)
2. Results cached in `UniverseStockORM` with `shares_outstanding` for inferred market cap
3. **Alpaca** provides live monitoring for non-filtered stocks (streaming prices via WebSocket)
4. Universe table ranked by today's return (from Alpaca snapshots), showing both market cap values, volume, live monitor status

### Files
- **MODIFY** `scanner/universe.py` — add `_discover_via_yfinance()` as alternative to Alpaca discovery. yfinance screener module can filter by price + market cap. Alpaca remains primary for live prices.
- **MODIFY** `dashboard/routes/universe.py` — compute today's return from Alpaca price cache, add `is_monitored` flag by cross-referencing `monitored_assets` table

---

## Phase 6: Telegram Bot Enhancements

**Goal:** Richer alert messages with account context, and order size specification via Telegram.

### 6a. Richer alert messages
- **MODIFY** `telegram_bot/formatters.py` — update `format_alert_message(report, broker=None, settings=None)`

The alert message should include ALL of:
- Current report data (recommendation, sentiment, fraud risk, key signals) — existing
- **Share price and how much it's up**: price + change % + timeframe (e.g., "+15.2% today" or "+8.3% in 2h")
- **Current penny stock positions**: count of open positions in penny stocks
- **Account value**: total account value, cash available
- **Position size context**: "Default order: £100" or "$50" or "10 shares"

New message format:
```
🚀 ALERT: $TICKER +15.2% | $1.23
━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Sentiment: 7.2/10 (85% confidence)
🔍 Sources: Reddit(12), StockTwits(45), SEC(2), News(5)
✅ Fraud Risk: LOW (1.2/10)
🤖 Recommendation: BUY

Key Signals:
  • ✅ High social media momentum
  • ⚠️ Low institutional ownership

💰 Account: £5,230 (£2,100 cash)
📦 Penny Positions: 4 open
💷 Default Order: £100

Consensus from 3 LLMs
```

### 6b. Order size specification in Telegram messages
- **MODIFY** `telegram_bot/handlers/callbacks.py`
- **MODIFY** `telegram_bot/handlers/commands.py`

When user presses BUY button or sends a buy command, allow specifying size:
- `/buy TICKER £50` — buy £50 worth
- `/buy TICKER $100` — buy $100 worth
- `/buy TICKER 25` — buy 25 shares
- `/buy TICKER` — use default position size from settings

Parse the order size from the message text. If £ prefix → GBP value, if $ prefix → USD value, if plain number → shares.

### 6c. Pass broker + settings to alert formatter
- **MODIFY** `telegram_bot/handlers/alerts.py` — pass broker and settings to `format_alert_message()` so it can fetch account summary and position count
- **MODIFY** `telegram_bot/bot.py` — ensure broker reference is available to alert_listener

### Files to modify
- `telegram_bot/formatters.py` — richer format_alert_message
- `telegram_bot/handlers/alerts.py` — pass broker + settings context
- `telegram_bot/handlers/callbacks.py` — order size parsing from message
- `telegram_bot/handlers/commands.py` — `/buy` command with size parameter
- `telegram_bot/bot.py` — pass broker to alert_listener

---

## Phase 7: Polish & Branding

- **MODIFY** `dashboard/app.py` — title "Sentinel Terminal"
- **MODIFY** `main.py` — log branding
- **MODIFY** `dashboard_ui/src/App.jsx` — "Sentinel Terminal" in nav
- **MODIFY** `dashboard_ui/src/pages/Dashboard.jsx` — quick links to Research, Watchlist, Monitor with counts
- Consider adding monospace font for data-heavy pages (Bloomberg aesthetic)

---

## File Change Summary

**DELETE (1):** `data/fmp_provider.py`

**CREATE (16):**
- `data/yfinance_provider.py`
- `dashboard/routes/research.py`
- `dashboard/routes/watchlist.py`
- `dashboard/routes/monitor.py`
- `dashboard_ui/src/pages/Research.jsx`
- `dashboard_ui/src/pages/AssetResearch.jsx`
- `dashboard_ui/src/pages/Watchlist.jsx`
- `dashboard_ui/src/pages/LiveMonitor.jsx`
- `dashboard_ui/src/components/SearchBar.jsx`
- `dashboard_ui/src/components/CumulativeReturnChart.jsx`
- `dashboard_ui/src/components/YieldCurveChart.jsx`
- `dashboard_ui/src/components/NewsCard.jsx`
- `tests/test_yfinance_provider.py`
- `tests/test_research.py`
- `tests/test_watchlist.py`
- `tests/test_monitor.py`

**MODIFY (25+):**
- `pyproject.toml`, `config/settings.py`, `config/constants.py`, `core/models.py`, `core/events.py`
- `scanner/universe.py`, `sentiment/news_source.py`, `main.py`, `data/base.py`
- `db/models.py`, `dashboard/app.py`, `dashboard/deps.py`, `dashboard/ws.py`
- `dashboard/routes/health.py`, `dashboard/routes/settings.py`, `dashboard/routes/universe.py`
- `analysis/_prompt_helper.py` (add `build_research_prompt()`)
- `dashboard_ui/src/App.jsx`, `dashboard_ui/src/pages/Universe.jsx`, `dashboard_ui/src/pages/Dashboard.jsx`
- `telegram_bot/formatters.py`, `telegram_bot/handlers/alerts.py`, `telegram_bot/handlers/callbacks.py`, `telegram_bot/handlers/commands.py`, `telegram_bot/bot.py`
- `tests/test_config.py`, `tests/test_scanner.py`, `tests/test_sentiment.py`, `tests/test_dashboard.py`
- `README.md`, `CLAUDE_CODE_BRIEFING.md`

---

## Verification
1. `pytest tests/ -x -q` — all tests pass
2. `grep -ri "fmp" --include="*.py" --include="*.md" --include="*.jsx"` returns zero results
3. Start app → penny stock universe populates from Alpaca + yfinance enrichment
4. `/research` page: search works, Bloomberg news loads, yield curve renders, G10 rates table shows
5. `/research/AAPL` sub-page: metrics, return chart with overlay, Watch/Monitor/LLM Analyse/BUY buttons work
6. LLM Analyse button generates report with macro context + news headlines
7. `/watchlist` shows watched assets, persists across restarts
8. `/monitor` shows live-monitored assets with real-time prices
9. `/penny-stocks` ranks by today's return, shows both market cap values, volume, monitor status
10. Telegram alert includes account value, penny position count, share price momentum, default order size
11. Telegram `/buy TICKER £50` works with size specification
12. Settings page: no FMP references, has `market_cap_source` selector
13. `npm run build` succeeds
