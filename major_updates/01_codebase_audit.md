# Phase 1: Codebase Audit

## Objective

Systematically review every module for: duplicate code, process inefficiencies, fragile implementations, errors, missing tests. Evaluate DB schema and caching for production readiness. Remove the Polygon data provider.

## Sub-phases (each gets its own commit)

### Sub-phase 1a: Core infrastructure — `config/`, `core/`, `db/`

**Files to review:**
- `config/settings.py` — settings validation, type coercion, defaults
- `config/constants.py` — global constants
- `core/models.py` — Pydantic data models
- `core/events.py` — EventBus pub/sub
- `core/exceptions.py` — custom exception hierarchy
- `core/market_hours.py` — US market hours logic
- `core/rate_limiter.py` — rate limiting
- `core/logging.py` — structured logging setup
- `db/database.py` — SQLAlchemy async engine, session factory
- `db/models.py` — all ORM models
- `db/migrations/` — Alembic migration chain

**Checklist:**
- [ ] Settings: all env vars have correct types and sensible defaults
- [ ] Constants: no magic numbers scattered elsewhere
- [ ] Models: all fields have correct types, validators where needed
- [ ] EventBus: no race conditions, proper cleanup
- [ ] Exceptions: hierarchy makes sense, no bare Exception catches
- [ ] DB: indexes on frequently queried columns
- [ ] DB: FK constraints with appropriate ON DELETE behavior
- [ ] DB: WAL mode verified
- [ ] DB: session lifecycle correct (no leaked sessions)
- [ ] DB: Alembic migration chain is linear and consistent
- [ ] Rate limiter: handles concurrent requests correctly

### Sub-phase 1b: Data & broker layer — `broker/`, `data/`

**Files to review:**
- `broker/base.py` — abstract broker interface
- `broker/trading212.py` — Trading 212 implementation
- `broker/paper_broker.py` — paper trading simulator
- `broker/safe_broker.py` — safety wrapper
- `data/base.py` — abstract provider interface
- `data/alpaca_provider.py` — Alpaca WebSocket + REST
- `data/yfinance_provider.py` — yfinance screener + prices
- `data/t212_provider.py` — Trading 212 data helper
- `data/sec_edgar_utils.py` — SEC scraping
- `data/sec_13f_provider.py` — 13F filings + CUSIP mapping

**Actions:**
- [ ] **Remove `data/polygon_provider.py`** entirely
- [ ] Remove `polygon_api_key` from `config/settings.py`
- [ ] Remove Polygon from settings UI sections in `dashboard/routes/settings.py`
- [ ] Remove any Polygon imports/references across the codebase
- [ ] Remove Polygon from `pyproject.toml` dependencies (`polygon-api-client`)
- [ ] Remove any Polygon tests
- [ ] Review broker error handling — no silent failures
- [ ] Review paper broker P&L calculations
- [ ] Review Alpaca WebSocket reconnection logic
- [ ] Review yfinance rate limiting and error handling
- [ ] Review SEC scraping robustness (HTML parsing)
- [ ] In-memory price cache: verify TTL/staleness detection
- [ ] CUSIP cache: verify it doesn't grow unbounded

### Sub-phase 1c: Analysis & sentiment — `scanner/`, `sentiment/`, `analysis/`, `stats/`

**Files to review:**
- `scanner/momentum_scanner.py`, `scanner/breadth_scanner.py`, `scanner/universe.py`
- `sentiment/aggregator.py` and all source files
- `analysis/` — all analysers, fraud_detector, report/consensus generators
- `stats/core.py`, `stats/parametric.py`, `stats/regime.py`, `stats/risk_free.py`

**Checklist:**
- [ ] Scanner: fix any bugs (will be replaced in Phase 7 but should work until then)
- [ ] Sentiment sources: handle API failures gracefully
- [ ] LLM analysers: handle rate limits, timeouts, malformed responses
- [ ] Fraud detector: validate all inputs
- [ ] Report generator: handle missing data gracefully
- [ ] Stats: **DO NOT MODIFY** — document any issues in `math_errors.md`

### Sub-phase 1d: Dashboard API & services — `dashboard/`

**Files to review:**
- `dashboard/app.py` — app factory
- `dashboard/deps.py` — dependency injection / global state
- `dashboard/dependencies.py` — FastAPI dependency functions
- `dashboard/middleware.py` — CORS, request ID, exception handling
- `dashboard/ws.py` — WebSocket connection manager
- `dashboard/schemas.py` — shared response schemas
- `dashboard/services/portfolio_cache.py` — caching service
- All 25+ files in `dashboard/routes/`

**Checklist:**
- [ ] No N+1 query patterns in routes
- [ ] All endpoints return proper error responses (not bare 500s)
- [ ] All endpoints have proper input validation
- [ ] WebSocket: handles disconnects gracefully
- [ ] Portfolio cache: invalidation works correctly
- [ ] CORS: appropriate for production
- [ ] No duplicate code between route modules

### Sub-phase 1e: Frontend & tests — `dashboard_ui/`, `tests/`

**Files to review:**
- All 24 page components
- All 25 component files
- All 5 hooks
- All 3 utility files
- All 34 test files

**Checklist:**
- [ ] No React hooks violations (calling hooks conditionally/in loops)
- [ ] SectorHeatMap.jsx: fix the hooks-in-loop anti-pattern (calls useApi in a map)
- [ ] No unnecessary re-renders
- [ ] Error states handled in all data-fetching components
- [ ] Loading states shown consistently
- [ ] Every API endpoint has success + error tests
- [ ] Edge cases tested: empty responses, malformed data
- [ ] All existing tests pass

## Output

- Fix all issues found (except math/stats code)
- Create `major_updates/math_errors.md` documenting any math/stats issues found
- Ensure all tests pass after each sub-phase
