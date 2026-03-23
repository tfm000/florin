# Phase 6: Screener Redesign

## Changes

Enhanced screener replacing the dedicated Penny Stocks tab with a general-purpose asset screener supporting:
- Volume column in results
- Clickable column headers for sorting
- Return momentum filters (min/max, configurable time period)
- Asset type filter (stocks, bonds, commodities, indices)
- Save screener settings to "Trade Screeners" page

## Database Migration

### New table: `saved_screeners`

```sql
CREATE TABLE saved_screeners (
    id VARCHAR(16) PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    filters_json TEXT NOT NULL,        -- JSON blob of all filter params
    sort_by VARCHAR(50) DEFAULT 'intradaymarketcap',
    sort_asc BOOLEAN DEFAULT FALSE,
    is_alert_active BOOLEAN DEFAULT FALSE,    -- Phase 7
    max_alerts_per_day INTEGER DEFAULT 10,    -- Phase 7
    alerts_sent_today INTEGER DEFAULT 0,      -- Phase 7
    include_llm_report BOOLEAN DEFAULT FALSE, -- Phase 7
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

## Backend Implementation

### 1. Add `SavedScreenerORM` to `db/models.py`

### 2. Create Alembic migration

```bash
alembic revision --autogenerate -m "add saved_screeners table"
```

### 3. Enhance `dashboard/routes/screener.py`

**New query parameters:**
- `momentum_min: float` — minimum return % over the momentum period
- `momentum_max: float` — maximum return % over the momentum period
- `momentum_period: str` — one of: `1d`, `5d`, `1w`, `1mo`, `3mo`, `1y` (maps to yfinance history periods)
- `asset_type: str` — filter by `quoteType` (EQUITY, ETF, MUTUALFUND, INDEX, COMMODITY, CURRENCY, CRYPTOCURRENCY)

**Momentum implementation approach:**
1. Run the base yfinance screen query (price, market cap, sector, exchange filters)
2. For results that need momentum filtering, fetch historical data for the specified period
3. Calculate percentage return over that period
4. Filter results to those within [momentum_min, momentum_max]
5. To limit latency, apply momentum filter to the first 100 results only

**Add `volume` to `ScreenerResult`:**
The `avg_volume` field already exists. Ensure it's prominently exposed. Also add `regularMarketVolume` (current day volume) as a new `volume` field.

**New CRUD endpoints:**
```
POST   /api/screener/saved           — create saved screener
GET    /api/screener/saved           — list all saved screeners
GET    /api/screener/saved/{id}      — get one saved screener
PUT    /api/screener/saved/{id}      — update saved screener
DELETE /api/screener/saved/{id}      — delete saved screener
```

**Saved screener payload (POST/PUT):**
```json
{
    "name": "High Momentum Tech",
    "filters": {
        "price_min": 10,
        "price_max": 500,
        "market_cap_min": 1000000000,
        "sector": "Technology",
        "momentum_min": 5,
        "momentum_max": 50,
        "momentum_period": "1mo",
        "asset_type": "EQUITY"
    },
    "sort_by": "change_pct",
    "sort_asc": false
}
```

### 4. Register new routes

If saved screener endpoints are in a new router, register it in `dashboard/app.py`.

## Frontend Implementation

### 1. Update `Screener.jsx`

**New filter inputs:**
- Momentum Min (%) — number input
- Momentum Max (%) — number input
- Momentum Period — dropdown: Current Day, Last Day, 1 Week, 1 Month, Quarter, Year, Custom
- Asset Type — dropdown: All, Stocks, Bonds, Commodities, Indices, ETFs, Crypto

**Volume column:** Add between Price and Change% columns. Show `avg_volume` formatted with K/M/B suffixes.

**Sortable columns:**
- Click any column header to sort
- Track `sortColumn` and `sortDirection` in state
- Show ▲/▼ arrow on active sort column
- Client-side sort on the `results` array before rendering

**Save button:**
- "Save Screener" button in the header area
- On click: prompt for a unique name (modal or inline input)
- Calls `POST /api/screener/saved` with current filters + sort settings
- Show success/error feedback

**Load from preset:**
- Check URL for `?preset={id}` on mount
- If present, fetch `GET /api/screener/saved/{id}` and populate filters

### 2. Update `TradingScreeners.jsx`

- Fetch `GET /api/screener/saved` on mount
- Display as a list/cards with: name, filter summary, created date
- Click a row → navigate to `/screener?preset={id}`
- Delete button per row with confirmation
- Alert status column (for Phase 7 — show as disabled/greyed out for now)

## Files to Modify

- `db/models.py` — add SavedScreenerORM
- `dashboard/routes/screener.py` — add momentum/asset_type params, CRUD endpoints
- `dashboard/app.py` — register new routes if needed
- `dashboard_ui/src/pages/Screener.jsx` — volume column, sorting, new filters, save button
- `dashboard_ui/src/pages/TradingScreeners.jsx` — display saved screeners

## New Files

- `db/migrations/versions/xxx_saved_screeners.py`

## Testing

- Test momentum filter returns only assets within specified range
- Test CRUD for saved screeners (create, read, update, delete)
- Test name uniqueness constraint (409 on duplicate)
- Test loading a saved screener by ID populates correct filters
- Test column sorting for each column (ascending/descending toggle)
- Test asset type filter correctly filters results
- Test volume column displays correctly
- Test empty screener results handled gracefully
