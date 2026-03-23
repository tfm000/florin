# Phase 5: Trading Consolidation

## Changes

1. Merge Dashboard, Account, Trades, Stats under a "Trading" tab with sub-pages
2. Add "Trade Screeners" sub-page (scaffold for Phase 6)
3. Add Trading Settings sub-page with Trading, Broker, and Telegram sections
4. Make Research the home route (`/`)
5. Replace Settings nav tab with a gear icon in the navbar
6. Remove Scanner settings section entirely (replaced by per-screener configs in Phase 6)
7. Remove Penny Stocks from navigation

## Implementation

### 1. Extract settings components

Extract `SettingsSection` and `SettingField` from `Settings.jsx` into `dashboard_ui/src/components/SettingsWidgets.jsx` so both the system settings page and trading settings page can reuse them.

### 2. Create `TradingLayout.jsx`

New file: `dashboard_ui/src/pages/TradingLayout.jsx`

Sub-tabs: Overview, Account, Trades, Stats, Screeners, Settings

### 3. Create `TradingSettings.jsx`

New file: `dashboard_ui/src/pages/TradingSettings.jsx`

Renders settings sections filtered to IDs: `["trading", "broker", "telegram"]`
Uses shared `SettingsWidgets` components.

### 4. Create `TradingScreeners.jsx`

New file: `dashboard_ui/src/pages/TradingScreeners.jsx`

Scaffold for now — displays "No saved screeners" with a link to the Screener page. Will be populated in Phase 6.

### 5. Update `Settings.jsx`

- Import shared components from `SettingsWidgets.jsx`
- Remove sections: `trading`, `broker`, `telegram`, `scanner`
- Keep sections: `market_data`, `sentiment`, `llm`, `analysis`, `general`
- Keep the Display/Colorblind toggle section

### 6. Update `dashboard/routes/settings.py`

Remove the `scanner` section from `_SECTIONS`:
```python
# Remove this entire block:
{
    "id": "scanner",
    "label": "Scanner",
    "keys": [...],
},
```

### 7. Update `App.jsx`

**New NAV_ITEMS:**
```javascript
const NAV_ITEMS = [
  { path: '/', label: 'Research' },
  { path: '/monitoring', label: 'Monitoring' },
  { path: '/screener', label: 'Screener' },
  { path: '/13f', label: '13F' },
  { path: '/news', label: 'News' },
  { path: '/calendar', label: 'Calendar' },
  { path: '/reports', label: 'Reports' },
  { path: '/portfolio', label: 'Portfolio' },
  { path: '/data', label: 'Data' },
  { path: '/trading', label: 'Trading' },
]
```

**Gear icon for Settings** — add next to the Terminate button:
```jsx
<NavLink to="/settings" className={...}>
  {/* Gear SVG icon */}
</NavLink>
```

**New routes:**
```jsx
<Route path="/" element={<Research />} />
<Route path="/research" element={<Navigate to="/" replace />} />

<Route path="/trading" element={<TradingLayout />}>
  <Route index element={<Dashboard />} />
  <Route path="account" element={<Account />} />
  <Route path="trades" element={<TradeHistory />} />
  <Route path="stats" element={<Stats />} />
  <Route path="screeners" element={<TradingScreeners />} />
  <Route path="settings" element={<TradingSettings />} />
</Route>

<Route path="/settings" element={<Settings />} />

{/* Redirects for old paths */}
<Route path="/account" element={<Navigate to="/trading/account" replace />} />
<Route path="/trades" element={<Navigate to="/trading/trades" replace />} />
<Route path="/stats" element={<Navigate to="/trading/stats" replace />} />
<Route path="/penny-stocks" element={<Navigate to="/screener" replace />} />
<Route path="/universe" element={<Navigate to="/screener" replace />} />
```

### 8. Update `Dashboard.jsx`

- Update links: `/settings` → `/trading/settings`, `/penny-stocks` → `/screener`
- Update quick links to reflect new paths

## Files to Modify

- `dashboard_ui/src/App.jsx`
- `dashboard_ui/src/pages/Settings.jsx`
- `dashboard_ui/src/pages/Dashboard.jsx`
- `dashboard/routes/settings.py` (remove scanner section)

## New Files

- `dashboard_ui/src/pages/TradingLayout.jsx`
- `dashboard_ui/src/pages/TradingSettings.jsx`
- `dashboard_ui/src/pages/TradingScreeners.jsx`
- `dashboard_ui/src/components/SettingsWidgets.jsx`

## Testing

- Verify Research loads at `/`
- Verify old `/research` redirects to `/`
- Verify all Trading sub-tabs render correctly
- Verify TradingSettings shows only Trading, Broker, Telegram sections
- Verify system Settings page shows only Market Data, Sentiment, LLM, Analysis, General, Display
- Verify gear icon navigates to `/settings`
- Verify all old path redirects work
- Verify no scanner settings appear anywhere
- Build frontend and verify no errors
