// Single source of truth for the `/research/asset/{ticker}/history` URL.
//
// REQ FND-02: every consumer of the asset-history endpoint MUST build its
// URL through this helper. The corresponding grep gate is enforced by
// the verify block in 01-PLAN.md task T-05.
//
// Returns { url, meta } so callers that need to know the effective period
// or interval (e.g. for downstream cache keys or display) can read it
// without re-deriving from the inputs.
//
// The url returned is the **path + query** form expected by useApi, which
// prepends `/api` itself. Callers using raw `fetch` (e.g. DataDownload's
// CSV export path) must prepend `/api` manually.

import { INTRADAY_TO_HISTORY } from './periods'

export function buildHistoryQuery({
  ticker,
  period,
  customStart,
  customEnd,
  interval = '1d',
  adjusted = true,
}) {
  const parts = []
  let effectiveInterval = interval
  let effectivePeriod = period

  if (customStart && customEnd) {
    parts.push(`start=${customStart}`, `end=${customEnd}`, `interval=${interval}`)
    effectivePeriod = 'custom'
  } else {
    const intraday = INTRADAY_TO_HISTORY[period]
    if (intraday) {
      parts.push(`period=${intraday.period}`, `interval=${intraday.interval}`)
      effectiveInterval = intraday.interval
      effectivePeriod = intraday.period
    } else {
      parts.push(`period=${period}`, `interval=${interval}`)
    }
  }

  if (!adjusted) parts.push('adjusted=false')

  return {
    url: `/research/asset/${ticker}/history?${parts.join('&')}`,
    meta: { interval: effectiveInterval, effectivePeriod },
  }
}
