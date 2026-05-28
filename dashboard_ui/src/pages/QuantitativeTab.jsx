import { useState, useMemo } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { buildRegimeQuery } from '../utils/regimeQuery'
import { usePriceHistory } from '../hooks/charts/usePriceHistory'
import MetricsGrid from '../components/MetricsGrid'
import PeriodSelector, { INTRADAY_TO_HISTORY, INTRADAY_KEYS } from '../components/PeriodSelector'
import PriceHistoryChart from '../components/charts/PriceHistoryChart'
import ReturnsHistogram from '../components/ReturnsHistogram'
import SearchBar from '../components/SearchBar'
import RiskMetrics from '../components/RiskMetrics'
import ShortInterestChart from '../components/ShortInterestChart'
import RegimeOverlay from '../components/RegimeOverlay'

export default function QuantitativeTab() {
  const { ticker } = useOutletContext()

  // Period state
  const [period, setPeriod] = useState('1y')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')

  // Comparison overlays
  const [compareTickers, setCompareTickers] = useState([])

  // Regime settings
  const [regimeNRegimes, setRegimeNRegimes] = useState(2)
  const [regimeSource, setRegimeSource] = useState('')

  // Line / candle toggle — default 'line' (UX-conservative, preserves existing behavior per D-10)
  const [mode, setMode] = useState('line')

  // Map intraday keys to valid yfinance periods for non-chart API calls
  const intradayMap = INTRADAY_TO_HISTORY[period]
  const isIntraday = INTRADAY_KEYS.has(period)
  const effectivePeriod = intradayMap?.period || period

  // Regime data fetch — URL flows through shared builder (REQ FND-03).
  const regimeInterval = intradayMap ? intradayMap.interval : '1d'
  const { url: regimeUrl } = buildRegimeQuery({
    ticker,
    period: effectivePeriod,
    customStart,
    customEnd,
    nRegimes: regimeNRegimes,
    interval: regimeInterval,
    source: regimeSource || undefined,
  })
  const { data: regimeData, loading: regimeLoading } = useApi(regimeUrl)

  // Primary price history fetch (D-11 — comparison hooks moved inline per D-11).
  const { data: primary, loading, error, stale } = usePriceHistory({
    ticker,
    period: effectivePeriod,
    customStart,
    customEnd,
  })

  // Comparison ticker fetches — 4 slots, each gated by an enabled flag (mirrors CRC:31-34).
  // usePriceHistory returns null data when enabled=false, so destructuring is safe.
  const { data: cmp0 } = usePriceHistory({ ticker: compareTickers[0], period: effectivePeriod, customStart, customEnd, enabled: !!compareTickers[0] })
  const { data: cmp1 } = usePriceHistory({ ticker: compareTickers[1], period: effectivePeriod, customStart, customEnd, enabled: !!compareTickers[1] })
  const { data: cmp2 } = usePriceHistory({ ticker: compareTickers[2], period: effectivePeriod, customStart, customEnd, enabled: !!compareTickers[2] })
  const { data: cmp3 } = usePriceHistory({ ticker: compareTickers[3], period: effectivePeriod, customStart, customEnd, enabled: !!compareTickers[3] })

  // Stable reference for cmpData (D-07 — prevents unnecessary chartData re-renders
  // caused by a new array literal being created each render).
  const cmpData = useMemo(() => [cmp0, cmp1, cmp2, cmp3], [cmp0, cmp1, cmp2, cmp3])

  // Series descriptor array consumed by PriceHistoryChart — primary ticker first,
  // then any active comparison tickers (D-11 / PATTERNS.md §QuantitativeTab.jsx).
  const series = useMemo(
    () => [
      { key: ticker, label: ticker, isPrimary: true },
      ...compareTickers.map(sym => ({ key: sym, label: sym })),
    ],
    [ticker, compareTickers],
  )

  // Merge primary history with comparison data into a single pre-shaped array
  // that PriceHistoryChart's internal chartData useMemo can consume (Path A per
  // PLAN.md §D-07+D-11 reconciliation: PriceHistoryChart ships with pre-merged data
  // prop; QuantitativeTab does the merge here so the chart remains fetch-free).
  //
  // In comparison mode each row gets a key per comparison ticker containing the
  // pre-computed cumulative percent return from each ticker's own t=0 base price.
  // PriceHistoryChart's chartData useMemo then reads `h[sym]` directly.
  //
  // In price mode the primary rows are passed through unchanged; PriceHistoryChart
  // handles OHLCV extraction internally.
  const mergedData = useMemo(() => {
    if (!primary || primary.length === 0) return []
    if (compareTickers.length === 0) return primary

    return primary.map((h, i) => {
      const row = { ...h }
      compareTickers.forEach((sym, ci) => {
        const cmpArr = cmpData[ci]
        if (cmpArr && cmpArr[i] && cmpArr[0]) {
          row[sym] = ((cmpArr[i].close - cmpArr[0].close) / cmpArr[0].close) * 100
        }
      })
      return row
    })
  }, [primary, cmpData, compareTickers])

  const handlePeriodChange = (p) => {
    setPeriod(p)
    setCustomStart('')
    setCustomEnd('')
  }

  const handleCustomRange = (start, end) => {
    setPeriod('custom')
    setCustomStart(start)
    setCustomEnd(end)
  }

  const handleAddCompare = (item) => {
    const sym = item.ticker.toUpperCase()
    if (sym !== ticker && !compareTickers.includes(sym)) {
      setCompareTickers(prev => [...prev, sym].slice(0, 4))
    }
  }

  const handleRemoveCompare = (sym) => {
    setCompareTickers(prev => prev.filter(t => t !== sym))
  }

  // Fetch stats from canonical server-side computation
  const statsQuery = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}`
    : `period=${effectivePeriod}`
  const { data: periodStats } = useApi(`/stats/returns/${ticker}?${statsQuery}`)

  const showReturns = !ticker.startsWith('^') && !ticker.includes('=')

  const periodMetrics = periodStats ? [
    { label: 'Return', value: periodStats.total_return, format: 'pct',
      color: periodStats.total_return >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: 'Sharpe', value: periodStats.sharpe, format: 'number' },
    { label: 'Max Drawdown', value: -periodStats.max_drawdown, format: 'pct' },
    { label: 'Ann. Volatility', value: periodStats.annualized_volatility, format: 'pct' },
  ] : []

  return (
    <div className="space-y-6">
      {/* Period selector + compare search */}
      <div className="bg-gray-800 rounded-lg p-3 border border-gray-700 space-y-3">
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Period</span>
          <PeriodSelector
            period={period}
            onPeriodChange={handlePeriodChange}
            startDate={customStart}
            endDate={customEnd}
            onCustomRange={handleCustomRange}
          />
          {/* Line / candle toggle — adjacent to PeriodSelector per D-10.
              Candle mode is unavailable when comparison series are active because
              comparison mode renders cumulative-% lines, not OHLC bars. The button
              is disabled (greyed out + cursor-not-allowed) to give the user clear
              feedback rather than silently ignoring the click. */}
          <div className="flex items-center gap-1 ml-auto">
            <button
              onClick={() => setMode('line')}
              className={`px-2 py-0.5 text-xs rounded ${mode === 'line' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}
            >
              Line
            </button>
            <button
              onClick={() => compareTickers.length === 0 && setMode('candle')}
              disabled={compareTickers.length > 0}
              title={compareTickers.length > 0 ? 'Candle mode unavailable with comparison series' : ''}
              className={`px-2 py-0.5 text-xs rounded ${
                compareTickers.length > 0
                  ? 'bg-gray-700 text-gray-600 cursor-not-allowed'
                  : mode === 'candle'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:text-white'
              }`}
            >
              Candle
            </button>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Compare</span>
          <SearchBar onSelect={handleAddCompare} placeholder="Add overlay..." />
          {compareTickers.map(sym => (
            <span key={sym} className="flex items-center gap-1 bg-gray-700 rounded px-2 py-0.5 text-xs text-white font-mono">
              {sym}
              <button onClick={() => handleRemoveCompare(sym)} className="text-gray-400 hover:text-red-400 ml-1">&times;</button>
            </span>
          ))}
        </div>
      </div>

      {/* Period-aware stats */}
      {periodMetrics.length > 0 && (
        <MetricsGrid metrics={periodMetrics} />
      )}

      {/* Price chart — migrated to PriceHistoryChart per D-09 */}
      <PriceHistoryChart
        data={mergedData}
        series={series}
        features={{
          regime: { data: regimeData },
          indicators: true,
          volume: true,
          candle: mode === 'candle',
        }}
        intraday={isIntraday}
        loading={loading}
        stale={stale}
        error={error}
        currency="USD"
        height={280}
      />

      {/* Returns histogram */}
      {showReturns && (
        <ReturnsHistogram
          ticker={ticker}
          period={period}
          customStart={customStart}
          customEnd={customEnd}
          compareTickers={compareTickers}
          regimeData={regimeData}
        />
      )}

      {/* Risk Metrics */}
      {showReturns && (
        <RiskMetrics ticker={ticker} period={period} customStart={customStart} customEnd={customEnd} />
      )}

      {/* Short Interest */}
      {showReturns && (
        <ShortInterestChart ticker={ticker} />
      )}

      {/* Regime Detection */}
      {showReturns && (
        <RegimeOverlay
          ticker={ticker}
          regimeData={regimeData}
          loading={regimeLoading}
          nRegimes={regimeNRegimes}
          source={regimeSource}
          isIntraday={isIntraday}
          onNRegimesChange={setRegimeNRegimes}
          onSourceChange={setRegimeSource}
        />
      )}
    </div>
  )
}
