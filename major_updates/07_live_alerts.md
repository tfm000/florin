# Phase 7: Live Alerts from Saved Screeners

## Changes

Users can activate "live alerts" on saved screener settings. When activated, the system periodically runs the screener and sends Telegram notifications for any new assets that enter the filter criteria. Optional LLM report inclusion. Trading212 order execution via Telegram chat.

This phase also **removes the old penny-stock scanner infrastructure** (`scanner/momentum_scanner.py`, `scanner/universe.py`) as its functionality is replaced by the screener alert service.

## Database Migration

### New table: `screener_alert_log`

```sql
CREATE TABLE screener_alert_log (
    id VARCHAR(16) PRIMARY KEY,
    screener_id VARCHAR(16) NOT NULL REFERENCES saved_screeners(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL,
    price FLOAT,
    alert_data_json TEXT,
    sent_at DATETIME NOT NULL
);
CREATE INDEX ix_screener_alert_log_screener_date ON screener_alert_log(screener_id, sent_at);
```

### Modify `saved_screeners` table

Add columns:
- `last_run_at: DateTime nullable`
- `run_interval_seconds: Integer default 300`

## Backend Implementation

### 1. Add `ScreenerAlertLogORM` to `db/models.py`

### 2. Create Alembic migration

### 3. Add `SCREENER_ALERT` to `EventType` in `core/events.py`

### 4. Create `scanner/screener_alert_service.py`

```python
class ScreenerAlertService:
    """Background service that runs active saved screeners and publishes alerts."""

    def __init__(self, db, yfinance_provider, event_bus):
        ...

    async def run(self):
        """Main loop — runs continuously, checking active screeners."""
        while True:
            active_screeners = await self._get_active_screeners()
            for screener in active_screeners:
                if self._should_run(screener):
                    await self._run_screener(screener)
            await asyncio.sleep(60)  # Check every minute

    async def _run_screener(self, screener):
        """Run a single screener and publish alerts for new matches."""
        # 1. Parse filters from filters_json
        # 2. Run the screen query (reuse screener route logic)
        # 3. Get today's already-alerted tickers from screener_alert_log
        # 4. Filter to new matches only
        # 5. Check alerts_sent_today < max_alerts_per_day
        # 6. Sort by screener's sort_by/sort_asc
        # 7. For each new match (top to bottom):
        #    a. Publish SCREENER_ALERT event
        #    b. Log to screener_alert_log
        #    c. Increment alerts_sent_today
        #    d. Stop if max reached
        # 8. Update last_run_at

    def _should_run(self, screener):
        """Check if enough time has passed since last run."""
        if screener.last_run_at is None:
            return True
        elapsed = (datetime.utcnow() - screener.last_run_at).total_seconds()
        return elapsed >= screener.run_interval_seconds

    async def _reset_daily_counters(self):
        """Reset alerts_sent_today to 0 at midnight."""
        # Called at start of each run cycle
        # Check if date has changed since last reset
```

### 5. Extract screener logic into shared function

Move the core screening logic from `dashboard/routes/screener.py` into a shared utility function that both the API endpoint and the alert service can call:

```python
# dashboard/services/screener_engine.py (new file)
async def run_screen(filters: dict, yf) -> list[ScreenerResult]:
    """Execute a stock screen with the given filters."""
    ...
```

### 6. Add screener alert service to `main.py`

```python
# In Sentinel.start():
screener_alert_svc = ScreenerAlertService(self.db, self.yf_provider, self.event_bus)
services.append(asyncio.create_task(
    screener_alert_svc.run(), name="screener-alerts"
))
```

### 7. Remove old scanner infrastructure

- Delete `scanner/momentum_scanner.py`
- Delete `scanner/universe.py`
- Keep `scanner/breadth_scanner.py` (market breadth is independent)
- Remove `UniverseManager` from `main.py`
- Remove `MomentumScanner` from `main.py`
- Remove scanner-related startup tasks
- Remove `scanner/base.py` if only used by momentum scanner
- Remove the `/api/universe` endpoint and `dashboard/routes/universe.py`
- Remove `UniverseStockORM` from `db/models.py` (or keep for migration compatibility)
- Remove Universe page from frontend (`dashboard_ui/src/pages/Universe.jsx`)
- Update any imports that reference removed modules

### 8. Telegram integration

**In `telegram_bot/handlers/alerts.py`:**
Add a second listener for `SCREENER_ALERT` events:
```python
async def screener_alert_listener(event_bus, bot, broker=None, settings=None):
    async for event in event_bus.subscribe(EventType.SCREENER_ALERT):
        screener_data = event.data
        # Format message
        message = format_screener_alert_message(screener_data)
        # Send via Telegram
        await bot.send_alert(message)

        # If include_llm_report and LLM is configured:
        #   Run analysis pipeline asynchronously
        #   Send follow-up message with report when ready

        # If Trading212 is configured:
        #   Add BUY/PASS inline keyboard buttons
```

**In `telegram_bot/formatters.py`:**
Add `format_screener_alert_message()`:
- Screener name
- Ticker, price, change %
- Why it matched (filter summary)
- Optional LLM report snippet

**In `telegram_bot/handlers/callbacks.py`:**
Add `screener_buy:{ticker}` callback:
- Places market order via broker (through SafeBroker for paper_trading safety)
- Confirms order execution in chat

### 9. API endpoints

```
PUT /api/screener/saved/{id}/activate   — toggle is_alert_active
GET /api/screener/saved/{id}/alerts     — get alert log for a screener
```

## Frontend Implementation

Update `TradingScreeners.jsx`:
- Alert toggle switch per screener (calls PUT activate endpoint)
- Max alerts/day editable field
- Run interval dropdown (1 min, 5 min, 15 min, 30 min, 1 hour)
- Include LLM report checkbox
- Expandable alert log section per screener showing recent alerts

## Files to Modify

- `db/models.py` — add ScreenerAlertLogORM, modify SavedScreenerORM
- `core/events.py` — add SCREENER_ALERT
- `main.py` — add screener alert service, remove old scanner
- `telegram_bot/bot.py` — add screener alert task
- `telegram_bot/handlers/alerts.py` — add screener alert listener
- `telegram_bot/handlers/callbacks.py` — add screener buy callback
- `telegram_bot/formatters.py` — add format_screener_alert_message
- `dashboard/routes/screener.py` — add activate/alerts endpoints
- `dashboard_ui/src/pages/TradingScreeners.jsx` — alert controls

## New Files

- `scanner/screener_alert_service.py`
- `dashboard/services/screener_engine.py`
- `db/migrations/versions/xxx_screener_alert_log.py`

## Files to Delete

- `scanner/momentum_scanner.py`
- `scanner/universe.py`
- `scanner/base.py` (if only used by momentum scanner)
- `dashboard/routes/universe.py`
- `dashboard_ui/src/pages/Universe.jsx`

## Testing

- Test alert deduplication: same ticker not alerted twice in one day per screener
- Test max alerts per day enforcement
- Test alert ordering matches sort configuration
- Test daily counter reset
- Test LLM report inclusion (optional, async)
- Test Trading212 buy from Telegram callback (behind SafeBroker)
- Test activate/deactivate toggle
- Test alert log retrieval
- Test screener alert service handles yfinance failures gracefully
- Verify removal of old scanner doesn't break remaining functionality
