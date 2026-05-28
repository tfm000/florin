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
import { buildIntradayQuery } from '../../utils/intradayQuery'

export function usePriceHistory({
  ticker,
  period,
  customStart,
  customEnd,
  enabled = true,
  interval = '1d',
  adjusted = true,
  intraday = false,
}) {
  const shouldFetch = enabled && !!ticker
  // Intraday → Alpaca (/quotes/intraday); daily/historical → yfinance (/history).
  // Design intent: intraday data comes from Alpaca for assets and portfolios
  // alike. In intraday mode `interval` is the intraday key itself (e.g. '5Min')
  // and period/customStart/customEnd are not part of the URL (the endpoint
  // defaults the range to the current session).
  const built = shouldFetch
    ? (intraday
        ? buildIntradayQuery({ ticker, interval })
        : buildHistoryQuery({ ticker, period, customStart, customEnd, interval, adjusted }))
    : { url: null, meta: { interval, effectivePeriod: period ?? null } }
  const { data, loading, error, stale, refetch } = useApi(built.url, { autoFetch: shouldFetch })
  return { data, loading, error, stale, refetch, meta: built.meta }
}
