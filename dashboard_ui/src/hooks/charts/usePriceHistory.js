// Layer-1 data hook for asset price-history charts.
//
// Per ARCHITECTURE.md three-layer model:
//   - Layer 1 (this file): owns URL construction (via buildHistoryQuery) +
//     data fetching (via useApi). Presentational chart components consume
//     this hook so they don't reach for fetch/useApi directly.
//   - Layer 2: presentational chart components (e.g. CumulativeReturnChart).
//   - Layer 3: page composers (QuantitativeTab, PortfolioDetail).
//
// Pass `enabled: false` (or an empty/falsy `ticker`) to short-circuit the
// fetch — useful for the comparison-overlay pattern where the slot may be
// empty. The hook still returns a stable shape so destructuring is safe.

import { useApi } from '../useApi'
import { buildHistoryQuery } from '../../utils/historyQuery'

export function usePriceHistory({
  ticker,
  period,
  customStart,
  customEnd,
  enabled = true,
  interval = '1d',
  adjusted = true,
}) {
  const shouldFetch = enabled && !!ticker
  const built = shouldFetch
    ? buildHistoryQuery({ ticker, period, customStart, customEnd, interval, adjusted })
    : { url: null, meta: { interval, effectivePeriod: period ?? null } }
  const { data, loading, error, stale, refetch } = useApi(built.url, { autoFetch: shouldFetch })
  return { data, loading, error, stale, refetch, meta: built.meta }
}
