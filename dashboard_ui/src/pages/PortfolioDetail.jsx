import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApi, apiPut, apiDelete, apiFetch } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import PeriodSelector, { INTRADAY_KEYS } from '../components/PeriodSelector'
import RegimeOverlay from '../components/RegimeOverlay'
import {
  ComposedChart, Line, Bar, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, ReferenceLine, Legend,
} from 'recharts'
import { useChartColors } from '../hooks/useChartColors'
import { useLegendToggle } from '../hooks/useLegendToggle'

const PIE_COLORS = ['#6366F1', '#22C55E', '#F59E0B', '#EF4444', '#EC4899', '#14B8A6', '#8B5CF6', '#F97316', '#06B6D4', '#D946EF']
const NUM_BINS = 40

// ---------------------------------------------------------------------------
// Histogram helpers (same formulas as ReturnsHistogram)
// ---------------------------------------------------------------------------

function buildBins(returns, globalMin, globalMax) {
  if (returns.length === 0 || globalMax === globalMin) return new Array(NUM_BINS).fill(0)
  const binWidth = (globalMax - globalMin) / NUM_BINS
  const counts = new Array(NUM_BINS).fill(0)
  for (const r of returns) {
    let idx = Math.floor((r - globalMin) / binWidth)
    if (idx >= NUM_BINS) idx = NUM_BINS - 1
    if (idx < 0) idx = 0
    counts[idx]++
  }
  return counts
}

function computeRegimeStats(returns) {
  if (returns.length === 0) return null
  const n = returns.length
  const mean = returns.reduce((s, r) => s + r, 0) / n
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (n - 1 || 1)
  const stdDev = Math.sqrt(variance)
  const skewness = n > 2 && stdDev > 0
    ? (n / ((n - 1) * (n - 2))) * returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 3, 0)
    : 0
  const kurtosis = n > 3 && stdDev > 0
    ? (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) *
      returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 4, 0) -
      3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    : 0
  const sorted = [...returns].sort((a, b) => a - b)
  const varIdx = Math.max(0, Math.floor(0.05 * n) - 1)
  const var95 = sorted[varIdx]
  const tailSlice = sorted.slice(0, varIdx + 1)
  const cvar95 = tailSlice.length > 0
    ? tailSlice.reduce((s, r) => s + r, 0) / tailSlice.length
    : var95
  const sharpe = stdDev > 0 ? (mean / stdDev) * Math.sqrt(252) : 0
  return { mean, stdDev, skewness, kurtosis, var95, cvar95, sharpe, n }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function PortfolioDetail() {
  const { portfolioId } = useParams()
  const navigate = useNavigate()
  const colors = useChartColors()
  const REGIME_COLORS = colors.regime

  const [period, setPeriod] = useState('1y')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [prorated, setProrated] = useState(false)
  const [pieView, setPieView] = useState('names')
  const [fundView, setFundView] = useState('weighted')
  const [editingDesc, setEditingDesc] = useState(false)
  const [descDraft, setDescDraft] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')

  // Chart & regime settings
  const [showRegimes, setShowRegimes] = useState(false)
  const [showHistRegimes, setShowHistRegimes] = useState(false)
  const [regimeNRegimes, setRegimeNRegimes] = useState(2)
  const [regimeSource, setRegimeSource] = useState('')

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  const { data: portfolios, refetch: refetchPortfolios } = useApi('/portfolios')
  const portfolio = portfolios?.find(p => p.id === portfolioId)
  const is13F = portfolio?.group === '13F'

  const isIntraday = INTRADAY_KEYS.has(period)

  const rangeQuery = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}` : `period=${period}`

  // --- Interday data (yfinance) — SSE with cache-then-refresh ---
  const { data: summary, stale: summaryStale } = useSSE(
    portfolioId && !isIntraday
      ? `/portfolios/${portfolioId}/summary/stream?${rangeQuery}&prorated=${prorated}`
      : null,
    { autoFetch: !!portfolioId && !isIntraday }
  )

  // Destructure summary into the same shapes downstream code expects
  const analytics = summary?.analytics ?? null
  const holdingsInfo = summary ? {
    portfolio_id: summary.portfolio_id,
    holdings: summary.holdings,
    weighted_pe: summary.weighted_pe,
    weighted_forward_pe: summary.weighted_forward_pe,
    weighted_dividend_yield: summary.weighted_dividend_yield,
    weighted_beta: summary.weighted_beta,
    avg_pe: summary.avg_pe,
    avg_forward_pe: summary.avg_forward_pe,
    avg_dividend_yield: summary.avg_dividend_yield,
    avg_beta: summary.avg_beta,
    max_pe: summary.max_pe,
    max_forward_pe: summary.max_forward_pe,
    max_dividend_yield: summary.max_dividend_yield,
    max_beta: summary.max_beta,
    min_pe: summary.min_pe,
    min_forward_pe: summary.min_forward_pe,
    min_dividend_yield: summary.min_dividend_yield,
    min_beta: summary.min_beta,
  } : null
  const returnsData = summary ? { portfolio_id: summary.portfolio_id, returns: summary.returns } : null

  // --- Progressive info enrichment for remaining holdings ---
  const [enrichedHoldings, setEnrichedHoldings] = useState(null)
  const enrichOffsetRef = useRef(0)
  const enrichAbortRef = useRef(false)

  // Reset progressive loading when summary changes
  useEffect(() => {
    setEnrichedHoldings(null)
    enrichOffsetRef.current = 0
    enrichAbortRef.current = true
  }, [portfolioId, rangeQuery, prorated])

  useEffect(() => {
    if (!summary || isIntraday) return
    const priceable = summary.priceable_count || 0
    const initialCount = summary.holdings?.filter(h => h.sector || h.pe_ratio != null).length || 0

    // If all holdings already have info, skip progressive loading
    if (initialCount >= priceable) return

    enrichAbortRef.current = false
    let offset = 50 // Start after the initial top 50 from /summary
    const limit = 50

    const loadNext = async () => {
      if (enrichAbortRef.current || offset >= priceable) return

      try {
        const data = await apiFetch(
          `/portfolios/${portfolioId}/holdings-info-page?offset=${offset}&limit=${limit}&${rangeQuery}`
        )
        if (enrichAbortRef.current) return

        setEnrichedHoldings(prev => {
          const map = {}
          // Build map from previous enrichments
          if (prev) for (const h of prev) map[h.ticker] = h
          // Merge new data
          for (const h of (data.holdings || [])) map[h.ticker] = h
          return Object.values(map)
        })

        offset += limit
        if (offset < priceable && !enrichAbortRef.current) {
          setTimeout(loadNext, 500)
        }
      } catch {
        // Stop on error — cached data from /summary still available
      }
    }

    loadNext()
    return () => { enrichAbortRef.current = true }
  }, [summary, portfolioId, rangeQuery, isIntraday])

  // Merge enriched holdings into holdingsInfo
  const mergedHoldingsInfo = useMemo(() => {
    if (!holdingsInfo) return null
    if (!enrichedHoldings) return holdingsInfo

    const enrichMap = {}
    for (const h of enrichedHoldings) enrichMap[h.ticker] = h

    return {
      ...holdingsInfo,
      holdings: holdingsInfo.holdings.map(h => enrichMap[h.ticker] || h),
    }
  }, [holdingsInfo, enrichedHoldings])

  // --- Intraday data (Alpaca bars) ---
  const { data: intradayReturns } = useApi(
    portfolioId && isIntraday ? `/portfolios/${portfolioId}/intraday/returns?interval=${period}` : null,
    { autoFetch: !!portfolioId && isIntraday, interval: isIntraday ? 30000 : null }
  )
  const { data: intradayAnalytics } = useApi(
    portfolioId && isIntraday ? `/portfolios/${portfolioId}/intraday/analytics?interval=${period}` : null,
    { autoFetch: !!portfolioId && isIntraday, interval: isIntraday ? 30000 : null }
  )

  const rawChartData = isIntraday
    ? (intradayReturns?.returns || []).map(p => ({ date: p.timestamp, portfolio: p.portfolio }))
    : (returnsData?.returns || [])

  // Regime data: interday only
  const regimeRangeParam = customStart && customEnd
    ? `&start=${customStart}&end=${customEnd}` : `&period=${period}`
  const regimePath = isIntraday ? null : (regimeSource
    ? `/regime/${regimeSource}?n_regimes=${regimeNRegimes}${regimeRangeParam}`
    : portfolioId ? `/portfolios/${portfolioId}/regime?n_regimes=${regimeNRegimes}${regimeRangeParam}` : null)
  const { data: regimeData, loading: regimeLoading } = useApi(regimePath, { autoFetch: !!regimePath })

  // ---------------------------------------------------------------------------
  // Enriched chart data with regime shading
  // ---------------------------------------------------------------------------

  const regimeMap = useMemo(() => {
    if (!regimeData?.regimes) return {}
    const map = {}
    for (const r of regimeData.regimes) map[r.date] = r.regime
    return map
  }, [regimeData])

  const chartData = useMemo(() => {
    if (!rawChartData.length) return []
    return rawChartData.map(pt => ({
      ...pt,
      regime: regimeMap[pt.date] ?? null,
      regimeBar: regimeMap[pt.date] != null ? 1 : 0,
    }))
  }, [rawChartData, regimeMap])

  // Y-axis domain with 5% padding
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [0, 1]
    const values = chartData.map(d => d.portfolio).filter(v => v != null)
    if (values.length === 0) return [0, 1]
    const min = Math.min(...values)
    const max = Math.max(...values)
    const padding = (max - min) * 0.05 || 1
    return [min - padding, max + padding]
  }, [chartData])

  // ---------------------------------------------------------------------------
  // Histogram data
  // ---------------------------------------------------------------------------

  const nRegimes = regimeData?.stats?.length || 0
  const regimeKeys = useMemo(() =>
    Array.from({ length: nRegimes }, (_, i) => `regime_${i}`),
    [nRegimes]
  )

  const { histData, portfolioStats, histRegimeStats } = useMemo(() => {
    // Compute daily returns from cumulative return series
    const dailyReturns = []
    const dailyDates = []
    for (let i = 1; i < chartData.length; i++) {
      const ret = chartData[i].portfolio - chartData[i - 1].portfolio
      dailyReturns.push(ret)
      dailyDates.push(chartData[i].date)
    }

    if (dailyReturns.length === 0) return { histData: [], portfolioStats: null, histRegimeStats: {} }

    // Split by regime
    const regimeReturns = {}
    if (showHistRegimes && Object.keys(regimeMap).length > 0) {
      for (let i = 0; i < dailyReturns.length; i++) {
        const regime = regimeMap[dailyDates[i]]
        if (regime == null) continue
        const key = `regime_${regime}`
        if (!regimeReturns[key]) regimeReturns[key] = []
        regimeReturns[key].push(dailyReturns[i])
      }
    }

    const showingRegimeSplit = showHistRegimes && Object.keys(regimeReturns).length > 0
    const allValues = showingRegimeSplit
      ? Object.values(regimeReturns).flat()
      : dailyReturns
    const globalMin = Math.min(...allValues)
    const globalMax = Math.max(...allValues)
    const binWidth = (globalMax - globalMin) / NUM_BINS || 1

    let histData
    if (showingRegimeSplit) {
      const binArrays = {}
      for (const [key, returns] of Object.entries(regimeReturns)) {
        binArrays[key] = buildBins(returns, globalMin, globalMax)
      }
      histData = Array.from({ length: NUM_BINS }, (_, i) => {
        const mid = globalMin + (i + 0.5) * binWidth
        const row = { bin: mid }
        for (const key of Object.keys(regimeReturns)) {
          row[key] = binArrays[key]?.[i] || 0
        }
        return row
      })
    } else {
      const bins = buildBins(dailyReturns, globalMin, globalMax)
      histData = Array.from({ length: NUM_BINS }, (_, i) => ({
        bin: globalMin + (i + 0.5) * binWidth,
        Portfolio: bins[i],
      }))
    }

    const portfolioStats = computeRegimeStats(dailyReturns)

    const histRegimeStats = {}
    for (const [key, returns] of Object.entries(regimeReturns)) {
      histRegimeStats[key] = computeRegimeStats(returns)
    }

    return { histData, portfolioStats, histRegimeStats }
  }, [chartData, showHistRegimes, regimeMap])

  // ---------------------------------------------------------------------------
  // Pie + table data
  // ---------------------------------------------------------------------------

  // Holdings pagination
  const [holdingsPage, setHoldingsPage] = useState(0)
  const HOLDINGS_PAGE_SIZE = 50

  const pieData = useMemo(() => {
    const holdings = mergedHoldingsInfo?.holdings || []
    if (pieView === 'names') {
      return holdings.map(h => ({ name: h.ticker, value: Math.round(h.weight * 10) / 10 }))
    }
    const key = pieView === 'sectors' ? 'sector' : 'industry'
    const agg = {}
    for (const h of holdings) {
      const label = h[key] || 'Unknown'
      agg[label] = (agg[label] || 0) + h.weight
    }
    return Object.entries(agg)
      .map(([name, value]) => ({ name, value: Math.round(value * 10) / 10 }))
      .sort((a, b) => b.value - a.value)
  }, [mergedHoldingsInfo, pieView])

  // Determine which pie slices get visible labels (>5% weight, max 10)
  const labelledNames = useMemo(() => {
    const sorted = [...pieData].sort((a, b) => b.value - a.value)
    return new Set(sorted.filter(d => d.value > 5).slice(0, 10).map(d => d.name))
  }, [pieData])

  const tableData = useMemo(() => {
    const holdings = mergedHoldingsInfo?.holdings || []
    if (pieView === 'names') return holdings
    const key = pieView === 'sectors' ? 'sector' : 'industry'
    const agg = {}
    for (const h of holdings) {
      const label = h[key] || 'Unknown'
      if (!agg[label]) agg[label] = { name: label, weight: 0, count: 0 }
      agg[label].weight += h.weight
      agg[label].count += 1
    }
    return Object.values(agg).sort((a, b) => b.weight - a.weight)
  }, [mergedHoldingsInfo, pieView])

  const pagedTableData = useMemo(() => {
    if (pieView !== 'names') return tableData
    const start = holdingsPage * HOLDINGS_PAGE_SIZE
    return tableData.slice(start, start + HOLDINGS_PAGE_SIZE)
  }, [tableData, holdingsPage, pieView])
  const totalPages = pieView === 'names' ? Math.ceil(tableData.length / HOLDINGS_PAGE_SIZE) : 1

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handlePeriodChange = (p) => { setPeriod(p); setCustomStart(''); setCustomEnd('') }
  const handleCustomRange = (s, e) => { setPeriod('custom'); setCustomStart(s); setCustomEnd(e) }

  const saveDescription = async () => {
    await apiPut(`/portfolios/${portfolioId}`, { description: descDraft })
    setEditingDesc(false)
    refetchPortfolios()
  }

  const saveName = async () => {
    if (!nameDraft.trim()) return
    try {
      await apiPut(`/portfolios/${portfolioId}`, { name: nameDraft.trim() })
      setEditingName(false)
      refetchPortfolios()
    } catch { setEditingName(false) }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this portfolio and all its holdings?')) return
    await apiDelete(`/portfolios/${portfolioId}`)
    navigate('/portfolio')
  }

  const xInterval = Math.max(0, Math.floor(chartData.length / 8))

  if (!portfolio) return <p className="text-gray-500 p-8">Loading...</p>

  const showingHistRegimes = showHistRegimes && regimeKeys.length > 0 && Object.keys(histRegimeStats).length > 0
  const periodLabel = customStart && customEnd ? `${customStart} to ${customEnd}` : period.toUpperCase()

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <button onClick={() => navigate('/portfolio')} className="text-gray-500 hover:text-white text-sm">
              &larr; All Portfolios
            </button>
            <button onClick={handleDelete} className="px-2 py-0.5 text-xs bg-red-700 text-white rounded hover:bg-red-600">
              Delete
            </button>
          </div>
          <div className="flex items-center gap-3">
            {editingName && !is13F ? (
              <input value={nameDraft} onChange={e => setNameDraft(e.target.value)}
                onBlur={saveName} onKeyDown={e => e.key === 'Enter' && saveName()}
                autoFocus className="text-2xl font-bold bg-gray-800 border border-gray-600 rounded px-2 py-1 text-white" />
            ) : (
              <h1 className="text-2xl font-bold text-white">{portfolio.name}</h1>
            )}
            {!is13F && !editingName && (
              <button onClick={() => { setNameDraft(portfolio.name); setEditingName(true) }}
                className="text-gray-500 hover:text-white text-xs">edit</button>
            )}
            {is13F && <span className="text-xs bg-indigo-600/30 text-indigo-400 px-2 py-0.5 rounded">13F</span>}
            {summaryStale && <span className="text-xs text-amber-500 animate-pulse ml-2">Refreshing...</span>}
          </div>
          {editingDesc ? (
            <textarea value={descDraft} onChange={e => setDescDraft(e.target.value)}
              onBlur={saveDescription} autoFocus rows={2}
              className="mt-2 w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-300" />
          ) : (
            <p className="text-gray-500 text-sm mt-1 cursor-pointer hover:text-gray-300"
              onClick={() => { setDescDraft(portfolio.description || ''); setEditingDesc(true) }}>
              {portfolio.description || 'Click to add description...'}
            </p>
          )}
        </div>
      </div>

      {/* Period selector */}
      <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Period</span>
          <PeriodSelector period={period} onPeriodChange={handlePeriodChange}
            startDate={customStart} endDate={customEnd} onCustomRange={handleCustomRange} />
        </div>
      </div>

      {/* Cumulative return chart */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-white font-semibold">Portfolio Returns</h3>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-gray-400 text-xs">Regimes</span>
              <button onClick={() => setShowRegimes(!showRegimes)}
                className={`px-2 py-0.5 text-xs rounded ${showRegimes ? 'bg-amber-600 text-white' : 'bg-gray-700 text-gray-400'}`}>
                {showRegimes ? 'On' : 'Off'}
              </button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-gray-400 text-xs">Prorated</span>
              <button onClick={() => setProrated(!prorated)}
                className={`px-2 py-0.5 text-xs rounded ${prorated ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}>
                {prorated ? 'On' : 'Off'}
              </button>
            </div>
          </div>
        </div>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fill: '#9CA3AF', fontSize: 11 }} interval={xInterval}
                tickFormatter={v => {
                  if (isIntraday) {
                    const d = new Date(v)
                    return d.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' })
                  }
                  const d = new Date(v + 'T00:00:00')
                  return d.toLocaleDateString('en', { month: 'short', year: 'numeric' })
                }} />
              <YAxis domain={yDomain} tick={{ fill: '#9CA3AF', fontSize: 11 }}
                tickFormatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`}
                label={{ value: 'Return (%)', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }} />
              {showRegimes && <YAxis yAxisId="regime" hide domain={[0, 1]} />}
              <Tooltip
                contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#fff' }}
                labelFormatter={v => { const d = new Date(v + 'T00:00:00'); return d.toLocaleDateString('en', { day: 'numeric', month: 'short', year: 'numeric' }) }}
                formatter={(v, name) => {
                  if (name === 'regimeBar') return [null, null]
                  return [`${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, 'Portfolio']
                }}
              />
              {showRegimes && (
                <Bar yAxisId="regime" dataKey="regimeBar" legendType="none" isAnimationActive={false}
                  shape={({ x, width, payload, background }) => {
                    if (payload.regime == null) return null
                    const areaY = background?.y ?? 5
                    const areaH = background?.height ?? 250
                    return (
                      <rect x={x} y={areaY} width={width} height={areaH}
                        fill={REGIME_COLORS[payload.regime % REGIME_COLORS.length]} fillOpacity={0.12} />
                    )
                  }}
                />
              )}
              <Line type="monotone" dataKey="portfolio" stroke={colors.series[0]} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-sm py-8 text-center">
            {summary || intradayReturns ? 'No return data available.' : 'Loading chart data...'}
          </p>
        )}
      </div>

      {/* Returns histogram */}
      {histData.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h3 className="text-white font-semibold">Daily Returns Distribution</h3>
              <button onClick={() => setShowHistRegimes(!showHistRegimes)}
                className={`px-2 py-0.5 text-xs rounded ${showHistRegimes ? 'bg-amber-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}>
                Regimes
              </button>
            </div>
            <span className="text-xs text-gray-500">{portfolioStats?.n || 0} days · {periodLabel}</span>
          </div>

          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={histData} barCategoryGap={0} barGap={0}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="bin" tick={{ fill: '#9CA3AF', fontSize: 10 }}
                tickFormatter={v => `${v.toFixed(0)}%`}
                interval={Math.max(0, Math.floor(histData.length / 8))}
                label={{ value: 'Daily Return (%)', position: 'insideBottom', offset: -2, fill: '#6B7280', fontSize: 10 }} />
              <YAxis tick={{ fill: '#9CA3AF', fontSize: 10 }}
                label={{ value: 'Frequency', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }} />
              <Tooltip
                contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#fff' }}
                labelFormatter={v => `Return: ${Number(v).toFixed(2)}%`}
                formatter={(v, name) => {
                  const label = name.startsWith('regime_')
                    ? `Regime ${name.split('_')[1]} (${['Low Vol', 'High Vol', 'Med Vol'][Number(name.split('_')[1])] || ''})`
                    : name
                  return [v, label]
                }}
              />
              <ReferenceLine x={0} stroke="#6B7280" strokeWidth={1} />
              {!showingHistRegimes && portfolioStats && (
                <ReferenceLine x={portfolioStats.mean} stroke="#F59E0B" strokeDasharray="4 4" strokeWidth={1.5}
                  label={{ value: `μ=${portfolioStats.mean.toFixed(2)}%`, fill: '#F59E0B', fontSize: 9, position: 'top' }} />
              )}
              <Legend wrapperStyle={{ fontSize: 11, cursor: 'pointer' }} onClick={handleLegendClick}
                formatter={(value, entry) => {
                  const label = value.startsWith('regime_')
                    ? `Regime ${value.split('_')[1]} (${['Low Vol', 'High Vol', 'Med Vol'][Number(value.split('_')[1])] || ''})`
                    : value
                  return legendFormatter(label, entry)
                }}
              />
              {showingHistRegimes ? (
                regimeKeys.map((key) => {
                  const idx = Number(key.split('_')[1])
                  return (
                    <Area key={key} type="step" dataKey={key}
                      fill={REGIME_COLORS[idx % REGIME_COLORS.length]} fillOpacity={0.35}
                      stroke={REGIME_COLORS[idx % REGIME_COLORS.length]} strokeWidth={1.5}
                      hide={isHidden(key)} />
                  )
                })
              ) : (
                <Bar dataKey="Portfolio" fill={colors.series[0]} opacity={0.9} radius={[2, 2, 0, 0]}
                  hide={isHidden('Portfolio')} />
              )}
            </ComposedChart>
          </ResponsiveContainer>

          {/* Stats table */}
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500">
                  <th className="text-left px-2 py-1">{showingHistRegimes ? 'Regime' : 'Series'}</th>
                  <th className="text-right px-2 py-1">Mean</th>
                  <th className="text-right px-2 py-1">Std Dev</th>
                  <th className="text-right px-2 py-1">Skew</th>
                  <th className="text-right px-2 py-1">Ex. Kurt</th>
                  <th className="text-right px-2 py-1">VaR 95%</th>
                  <th className="text-right px-2 py-1">CVaR 95%</th>
                  <th className="text-right px-2 py-1">Sharpe</th>
                  <th className="text-right px-2 py-1">Days</th>
                </tr>
              </thead>
              <tbody>
                {showingHistRegimes ? (
                  regimeKeys.map((key) => {
                    const s = histRegimeStats[key]
                    if (!s) return null
                    const idx = Number(key.split('_')[1])
                    return (
                      <tr key={key} className="text-white">
                        <td className="px-2 py-1 font-mono flex items-center gap-1">
                          <span className="inline-block w-2 h-2 rounded"
                            style={{ backgroundColor: REGIME_COLORS[idx % REGIME_COLORS.length] }} />
                          R{idx} ({['Low Vol', 'High Vol', 'Med Vol'][idx]})
                        </td>
                        <td className={`text-right px-2 py-1 font-mono ${s.mean >= 0 ? 'text-green-400' : 'text-red-400'}`}>{s.mean.toFixed(3)}%</td>
                        <td className="text-right px-2 py-1 font-mono">{s.stdDev.toFixed(3)}%</td>
                        <td className="text-right px-2 py-1 font-mono">{s.skewness.toFixed(3)}</td>
                        <td className="text-right px-2 py-1 font-mono">{s.kurtosis.toFixed(3)}</td>
                        <td className="text-right px-2 py-1 font-mono text-red-400">{s.var95.toFixed(3)}%</td>
                        <td className="text-right px-2 py-1 font-mono text-red-400">{s.cvar95.toFixed(3)}%</td>
                        <td className="text-right px-2 py-1 font-mono">{s.sharpe.toFixed(2)}</td>
                        <td className="text-right px-2 py-1 font-mono text-gray-400">{s.n}</td>
                      </tr>
                    )
                  })
                ) : portfolioStats ? (
                  <tr className="text-white">
                    <td className="px-2 py-1 font-mono" style={{ color: colors.series[0] }}>Portfolio</td>
                    <td className={`text-right px-2 py-1 font-mono ${portfolioStats.mean >= 0 ? 'text-green-400' : 'text-red-400'}`}>{portfolioStats.mean.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{portfolioStats.stdDev.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{portfolioStats.skewness.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono">{portfolioStats.kurtosis.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{portfolioStats.var95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{portfolioStats.cvar95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{portfolioStats.sharpe.toFixed(2)}</td>
                    <td className="text-right px-2 py-1 font-mono text-gray-400">{portfolioStats.n}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Regime Detection — interday only */}
      {!isIntraday && (
        <RegimeOverlay
          ticker="Portfolio"
          regimeData={regimeData}
          loading={regimeLoading}
          nRegimes={regimeNRegimes}
          source={regimeSource}
          onNRegimesChange={setRegimeNRegimes}
          onSourceChange={setRegimeSource}
        />
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {isIntraday && intradayAnalytics && (
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <h3 className="text-white font-semibold mb-3">Intraday Analytics</h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="Daily Return" value={`${intradayAnalytics.daily_return}%`}
                color={intradayAnalytics.daily_return >= 0 ? 'text-green-400' : 'text-red-400'} />
              <Stat label="Daily Vol" value={`${intradayAnalytics.daily_vol}%`} />
            </div>
          </div>
        )}
        {!isIntraday && analytics && (
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <h3 className="text-white font-semibold mb-3">Portfolio Analytics</h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="Return" value={`${analytics.total_return}%`}
                color={analytics.total_return >= 0 ? 'text-green-400' : 'text-red-400'} />
              <Stat label="Ann. Volatility" value={`${analytics.annualized_vol}%`} />
              <Stat label="Sharpe" value={analytics.sharpe.toFixed(2)}
                color={analytics.sharpe >= 0 ? 'text-green-400' : 'text-red-400'} />
              <Stat label="Sortino" value={analytics.sortino.toFixed(2)}
                color={analytics.sortino >= 0 ? 'text-green-400' : 'text-red-400'} />
              <Stat label="Max Drawdown" value={`${analytics.max_drawdown}%`} color="text-red-400" />
              <Stat label="VaR (95%)" value={`${analytics.var_95}%`} color="text-red-400" />
              <Stat label="CVaR (95%)" value={`${analytics.cvar_95}%`} color="text-red-400" />
            </div>
          </div>
        )}

        {mergedHoldingsInfo && (() => {
          const prefix = fundView === 'weighted' ? 'weighted' : fundView
          const pe = mergedHoldingsInfo[`${prefix}_pe`]
          const fpe = mergedHoldingsInfo[`${prefix}_forward_pe`]
          const dy = mergedHoldingsInfo[`${prefix}_dividend_yield`]
          const beta = mergedHoldingsInfo[`${prefix}_beta`]
          return (
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-white font-semibold">Fundamentals</h3>
                <div className="flex gap-1">
                  {['weighted', 'avg', 'max', 'min'].map(v => (
                    <button key={v} onClick={() => setFundView(v)}
                      className={`px-2 py-0.5 text-xs rounded ${fundView === v ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}>
                      {v === 'avg' ? 'Average' : v.charAt(0).toUpperCase() + v.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <Stat label="P/E Ratio" value={pe?.toFixed(1) ?? '—'} />
                <Stat label="Forward P/E" value={fpe?.toFixed(1) ?? '—'} />
                <Stat label="Dividend Yield" value={dy != null ? `${(dy * 100).toFixed(2)}%` : '—'} />
                <Stat label="Beta" value={beta?.toFixed(2) ?? '—'} />
              </div>
            </div>
          )
        })()}
      </div>

      {/* Pie chart + allocation table */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold">Allocation</h3>
            <div className="flex gap-1">
              {['names', 'sectors', 'industries'].map(v => (
                <button key={v} onClick={() => setPieView(v)}
                  className={`px-2 py-0.5 text-xs rounded ${pieView === v ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}>
                  {v.charAt(0).toUpperCase() + v.slice(1)}
                </button>
              ))}
            </div>
          </div>
          {pieData.length > 0 && (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                  innerRadius={45} outerRadius={90}
                  label={({ name, value, x, y, textAnchor }) =>
                    labelledNames.has(name) ? (
                      <text x={x} y={y} textAnchor={textAnchor} fill="#D1D5DB" fontSize={10}>
                        {name} {value}%
                      </text>
                    ) : null
                  }
                  labelLine={({ name }) => labelledNames.has(name)}>
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={v => `${v}%`} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold">
              {pieView === 'names' ? 'Holdings' : pieView === 'sectors' ? 'Sectors' : 'Industries'}
              {pieView === 'names' && tableData.length > 0 && (
                <span className="text-gray-500 text-xs font-normal ml-2">({tableData.length} total)</span>
              )}
            </h3>
            {pieView === 'names' && totalPages > 1 && (
              <div className="flex items-center gap-2">
                <button onClick={() => setHoldingsPage(p => Math.max(0, p - 1))} disabled={holdingsPage === 0}
                  className="px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400 hover:text-white disabled:opacity-30">Prev</button>
                <span className="text-xs text-gray-400">{holdingsPage + 1} / {totalPages}</span>
                <button onClick={() => setHoldingsPage(p => Math.min(totalPages - 1, p + 1))} disabled={holdingsPage >= totalPages - 1}
                  className="px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400 hover:text-white disabled:opacity-30">Next</button>
              </div>
            )}
          </div>
          <div className="overflow-y-auto max-h-72">
            <table className="w-full text-xs">
              <thead className="bg-gray-900/50">
                <tr className="text-gray-400">
                  <th className="px-2 py-1 text-left">{pieView === 'names' ? 'Ticker' : 'Name'}</th>
                  <th className="px-2 py-1 text-right">Weight</th>
                  {pieView === 'names' && <th className="px-2 py-1 text-left">Sector</th>}
                  {pieView === 'names' && <th className="px-2 py-1 text-left">Industry</th>}
                  {pieView === 'names' && <th className="px-2 py-1 text-right">P/E</th>}
                  {pieView === 'names' && <th className="px-2 py-1 text-right">Return</th>}
                  {pieView === 'names' && <th className="px-2 py-1 text-right">Vol</th>}
                  {pieView !== 'names' && <th className="px-2 py-1 text-right">Holdings</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {pagedTableData.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-700/30"
                    onClick={() => pieView === 'names' && row.ticker && navigate(`/research/${row.ticker}`)}>
                    <td className={`px-2 py-1 font-mono text-white ${pieView === 'names' ? 'cursor-pointer' : ''}`}>
                      {pieView === 'names' ? row.ticker : row.name}
                    </td>
                    <td className="px-2 py-1 text-right text-gray-300">{row.weight.toFixed(1)}%</td>
                    {pieView === 'names' && <td className="px-2 py-1 text-gray-400 truncate max-w-24">{row.sector || '—'}</td>}
                    {pieView === 'names' && <td className="px-2 py-1 text-gray-400 truncate max-w-28">{row.industry || '—'}</td>}
                    {pieView === 'names' && <td className="px-2 py-1 text-right text-gray-400 font-mono">{row.pe_ratio?.toFixed(1) ?? '—'}</td>}
                    {pieView === 'names' && (
                      <td className={`px-2 py-1 text-right font-mono ${
                        row.period_return == null ? 'text-gray-400' : row.period_return >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {row.period_return != null ? `${row.period_return >= 0 ? '+' : ''}${row.period_return.toFixed(1)}%` : '—'}
                      </td>
                    )}
                    {pieView === 'names' && (
                      <td className="px-2 py-1 text-right text-gray-400 font-mono">
                        {row.period_vol != null ? `${row.period_vol.toFixed(1)}%` : '—'}
                      </td>
                    )}
                    {pieView !== 'names' && <td className="px-2 py-1 text-right text-gray-400">{row.count}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-gray-900/50 rounded-lg p-2.5">
      <p className="text-gray-500 text-xs uppercase">{label}</p>
      <p className={`font-mono text-sm ${color}`}>{value}</p>
    </div>
  )
}
