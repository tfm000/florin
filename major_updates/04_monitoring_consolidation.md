# Phase 4: Monitoring Consolidation

## Changes

Merge the "Watchlist" and "Live Monitor" tabs into a single "Monitoring" tab with sub-pages.

## Implementation

### 1. Create `MonitoringLayout.jsx`

New file: `dashboard_ui/src/pages/MonitoringLayout.jsx`

Layout component with:
- Sub-tab bar with two NavLinks: "Watchlist" (`/monitoring/watchlist`) and "Live" (`/monitoring/live`)
- `<Outlet />` for child route rendering
- Follow the same pattern as `AssetLayout.jsx` for sub-tab styling

### 2. Update `App.jsx`

**NAV_ITEMS changes:**
- Remove: `{ path: '/watchlist', label: 'Watchlist' }`
- Remove: `{ path: '/monitor', label: 'Live Monitor' }`
- Add: `{ path: '/monitoring', label: 'Monitoring' }`

**Route changes:**
```jsx
{/* Monitoring — nested routes */}
<Route path="/monitoring" element={<MonitoringLayout />}>
  <Route index element={<Navigate to="watchlist" replace />} />
  <Route path="watchlist" element={<Watchlist />} />
  <Route path="live" element={<LiveMonitor />} />
</Route>
<Route path="/monitoring/live/:ticker" element={<MonitorAsset />} />

{/* Redirects for old paths */}
<Route path="/watchlist" element={<Navigate to="/monitoring/watchlist" replace />} />
<Route path="/monitor" element={<Navigate to="/monitoring/live" replace />} />
<Route path="/monitor/:ticker" element={<Navigate to="/monitoring/live/:ticker" replace />} />
```

### 3. Update cross-references

- `Dashboard.jsx`: Update quick links from `/watchlist` → `/monitoring/watchlist` and `/monitor` → `/monitoring/live`
- `MonitorAsset.jsx` / `LiveMonitor.jsx`: Update any internal navigation links

## Files to Modify

- `dashboard_ui/src/App.jsx`
- `dashboard_ui/src/pages/Dashboard.jsx`
- `dashboard_ui/src/pages/LiveMonitor.jsx` (if it has links to `/monitor/:ticker`, update to `/monitoring/live/:ticker`)

## New Files

- `dashboard_ui/src/pages/MonitoringLayout.jsx`

## Testing

- Verify `/monitoring` redirects to `/monitoring/watchlist`
- Verify old paths `/watchlist` and `/monitor` redirect correctly
- Verify sub-tab navigation highlights the active tab
- Verify LiveMonitor WebSocket connection still works in nested route context
- Verify MonitorAsset page works at `/monitoring/live/:ticker`
- Build frontend and verify no console errors
