# Phase 3: Research Page Improvements

## Changes

### 3a. Two Pre-configured Correlation Matrices

Create a new `PresetCorrelationMatrix` component — a read-only correlation matrix that takes fixed ticker lists and display labels. Uses the existing `/api/correlation` endpoint.

**Matrix 1: Cross-Asset Correlation**
- Tickers: `SPY, ^FTSE, ^GDAXI, GC=F, CL=F, NG=F`
- Labels: `S&P 500, FTSE 100, DAX, Gold, Oil, Nat Gas`

**Matrix 2: S&P 500 Sector Correlation**
- Tickers: `XLK, XLV, XLF, XLY, XLP, XLE, XLI, XLB, XLU, XLRE, XLC`
- Labels: `Technology, Healthcare, Financials, Consumer Disc, Consumer Stpl, Energy, Industrials, Materials, Utilities, Real Estate, Comm Services`

### 3b. Batch Sector Endpoint

Currently `SectorHeatMap.jsx` makes 11 individual `useApi('/research/asset/{ETF}')` calls — one per sector. This is:
- Inefficient (11 HTTP requests)
- A React hooks anti-pattern (calling `useApi` in a loop with `eslint-disable` comment)

**New endpoint: `GET /api/research/sectors`**
- Fetches all 11 sector ETFs via `asyncio.gather` in one handler
- Returns: `{ sectors: [{ name, etf, price, market_cap, returns: { "1d": float, "1w": float, "1m": float, "3m": float, "6m": float, "1y": float } }] }`

**New endpoint: `GET /api/research/sectors/history?period=1m`**
- Returns aligned daily close prices for all sector ETFs
- Used for the cumulative returns line chart
- Returns: `{ dates: [string], series: { "Technology": [float], "Healthcare": [float], ... } }`

### 3c. Enhanced Sector Performance Chart

Replace `SectorHeatMap.jsx` with `SectorPerformanceChart.jsx`:

**Views (toggle between):**
1. **Heatmap** (default) — treemap visualization, same as current but using batch data
2. **Bar Chart** — horizontal bars sorted from lowest to highest return for the selected timeframe
3. **Line Chart** — cumulative return lines for each sector, using `useLegendToggle` for series visibility

**Timeframe selector:** 1D, 1W, 1M, 3M, 6M, 1Y

## Files to Modify

- `dashboard/routes/research.py` — add `/sectors` and `/sectors/history` endpoints
- `dashboard_ui/src/components/SectorHeatMap.jsx` — delete (replaced)
- `dashboard_ui/src/pages/Research.jsx` — add PresetCorrelationMatrix instances, swap SectorHeatMap for SectorPerformanceChart

## New Files

- `dashboard_ui/src/components/PresetCorrelationMatrix.jsx`
- `dashboard_ui/src/components/SectorPerformanceChart.jsx`

## Backend Implementation Detail

```python
# In dashboard/routes/research.py

SECTOR_ETFS = {
    "Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF",
    "Consumer Disc": "XLY", "Consumer Stpl": "XLP", "Energy": "XLE",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Comm Services": "XLC",
}

@router.get("/research/sectors")
async def get_sectors(yf=Depends(get_yfinance_dep)):
    """Batch fetch all S&P 500 sector ETF data."""
    # Fetch all 11 in parallel
    # For each: current price, market cap, returns at multiple timeframes
    # Return consolidated response

@router.get("/research/sectors/history")
async def get_sectors_history(
    period: str = Query(default="1m"),
    yf=Depends(get_yfinance_dep),
):
    """Get aligned daily close prices for all sector ETFs."""
    # Fetch all 11 histories in parallel
    # Align by common dates
    # Return dates + series
```

## Testing

- Test `/api/research/sectors` returns all 11 sectors with correct fields
- Test `/api/research/sectors/history` returns aligned date series with correct number of sectors
- Test correlation endpoint handles 6+ tickers (cross-asset matrix)
- Test correlation endpoint handles 11 tickers (sector matrix)
- Test empty/error responses from yfinance are handled gracefully
- Verify the existing `CorrelationMatrix` component still works (it's user-driven, not preset)
