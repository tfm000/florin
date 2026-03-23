# Phase 9: Final Codebase Audit

## Objective

Repeat the Phase 1 audit on the post-transformation codebase. The codebase has undergone major changes in Phases 2-8, so new errors, missing tests, and integration issues may have been introduced.

## Focus Areas

### 1. New code review

Review all new files created in Phases 2-8:
- `dashboard_ui/src/pages/MonitoringLayout.jsx`
- `dashboard_ui/src/pages/TradingLayout.jsx`
- `dashboard_ui/src/pages/TradingSettings.jsx`
- `dashboard_ui/src/pages/TradingScreeners.jsx`
- `dashboard_ui/src/components/SettingsWidgets.jsx`
- `dashboard_ui/src/components/PresetCorrelationMatrix.jsx`
- `dashboard_ui/src/components/SectorPerformanceChart.jsx`
- `scanner/screener_alert_service.py`
- `dashboard/services/screener_engine.py`
- All new migration files

### 2. Integration points

- Screener → Save → Trade Screeners flow
- Trade Screeners → Activate Alert → Telegram notification flow
- Telegram BUY callback → SafeBroker → order execution
- Research page correlation matrices with direct index tickers
- Sector performance chart with all three view modes
- Navigation: all redirects from old paths work
- Settings: system settings vs trading settings split

### 3. Regression testing

- All pre-existing functionality still works
- No broken imports from the rename
- No broken routes from the navigation restructure
- WebSocket events still flow correctly
- Portfolio analytics still work
- LLM analysis pipeline still functions

### 4. Test coverage

Ensure tests exist for:
- All new API endpoints (saved screeners CRUD, activate, alert log)
- SPA routing catch-all
- Sector batch endpoint
- Screener alert service (deduplication, daily limits, sort order)
- Telegram screener alert formatting
- Navigation redirects

### 5. Database consistency

- All new migrations apply cleanly on a fresh database
- All new migrations apply cleanly on an existing database
- FK constraints are correct
- Indexes are present on frequently queried columns

### 6. Performance

- Screener alert service doesn't cause excessive yfinance API calls
- Sector batch endpoint responds within reasonable time
- Correlation matrix with 11 tickers completes within acceptable time
- No memory leaks from the screener alert service loop

## Output

- Fix all issues found
- Update `major_updates/math_errors.md` if new math/stats issues are discovered
- Ensure all tests pass
- Document any remaining known issues
