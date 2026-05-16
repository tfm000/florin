import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { buildRegimeQuery } from '../utils/regimeQuery'
import MetricsGrid from '../components/MetricsGrid'
import PeriodSelector, { INTRADAY_TO_HISTORY, INTRADAY_KEYS } from '../components/PeriodSelector'
import CumulativeReturnChart from '../components/CumulativeReturnChart'
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

      {/* Price chart */}
      <CumulativeReturnChart
        ticker={ticker}
        period={period}
        customStart={customStart}
        customEnd={customEnd}
        compareTickers={compareTickers}
        regimeData={regimeData}
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
