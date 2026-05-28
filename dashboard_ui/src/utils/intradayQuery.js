// Single source of truth for the Alpaca-backed asset intraday endpoint URL.
//
// Design intent: intraday market data comes from **Alpaca** for individual
// assets, matching the portfolio detail page. yfinance (buildHistoryQuery) is
// for daily/historical only. The `/research/asset/{ticker}/quotes/intraday`
// endpoint returns OHLCV bars (Alpaca) merged with bid/ask quotes; the range
// defaults to the current session and is parameterised only by `interval`
// (one of 1Min, 5Min, 15Min, 30Min, 1Hour).
//
// Returns { url, meta }; `url` is the path+query form expected by useApi, which
// prepends `/api` itself. Mirrors buildHistoryQuery / buildRegimeQuery.

export function buildIntradayQuery({ ticker, interval = '5Min' }) {
  return {
    url: `/research/asset/${encodeURIComponent(ticker)}/quotes/intraday?interval=${interval}`,
    meta: { interval, effectivePeriod: 'intraday' },
  }
}
