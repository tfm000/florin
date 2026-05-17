// Single source of truth for regime-detection endpoint URLs.
//
// REQ FND-03: every consumer of `/regime/{ticker}` or
// `/portfolios/{id}/regime` MUST build its URL through this helper.
//
// Two URL shapes are produced from one builder:
//   - ticker-based: `/regime/{ticker}?n_regimes=X[&interval=Y][&source=Z][&period=P | &start=A&end=B]`
//   - portfolio-based: `/portfolios/{portfolioId}/regime?n_regimes=X[&source=Z][&period=P | &start=A&end=B]`
//
// Exactly one of `ticker` or `portfolioId` must be supplied. The
// portfolio path does not accept an `interval` argument today.

export function buildRegimeQuery({
  ticker,
  portfolioId,
  period,
  customStart,
  customEnd,
  nRegimes,
  interval,
  source,
}) {
  if (ticker && portfolioId) {
    throw new Error('buildRegimeQuery: supply either ticker OR portfolioId, not both')
  }
  if (!ticker && !portfolioId) {
    throw new Error('buildRegimeQuery: supply either ticker or portfolioId')
  }

  const parts = [`n_regimes=${nRegimes}`]
  if (interval) parts.push(`interval=${interval}`)
  if (source) parts.push(`source=${source}`)
  if (customStart && customEnd) {
    parts.push(`start=${customStart}`, `end=${customEnd}`)
  } else if (period) {
    parts.push(`period=${period}`)
  }

  const path = portfolioId
    ? `/portfolios/${portfolioId}/regime`
    : `/regime/${ticker}`

  const effectivePeriod = customStart && customEnd ? 'custom' : period

  return {
    url: `${path}?${parts.join('&')}`,
    meta: { effectivePeriod, interval, nRegimes },
  }
}
