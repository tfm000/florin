import { useState, useMemo } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'
import { useChartColors } from '../hooks/useChartColors'

const VIEWS = [
  { key: 'combined', label: 'Combined (OTM)' },
  { key: 'puts', label: 'Put Surface' },
  { key: 'calls', label: 'Call Surface' },
]

export default function PutCallIVChart({ initialTicker = 'SPY' }) {
  const colors = useChartColors()
  const [ticker, setTicker] = useState(initialTicker)
  const [inputVal, setInputVal] = useState(initialTicker)
  const [view, setView] = useState('combined')
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [compareExpiry, setCompareExpiry] = useState('')

  const { data, loading } = useApi(
    `/research/iv-spread?ticker=${ticker}${selectedExpiry ? `&expiry=${selectedExpiry}` : ''}`
  )
  const { data: compareData } = useApi(
    compareExpiry ? `/research/iv-spread?ticker=${ticker}&expiry=${compareExpiry}` : null,
    { autoFetch: !!compareExpiry }
  )

  const skewLegend = useLegendToggle()
  const termLegend = useLegendToggle()

  const handleSubmit = (e) => {
    e.preventDefault()
    setTicker(inputVal.toUpperCase())
    setSelectedExpiry('')
    setCompareExpiry('')
  }

  const skew = data?.skew || []
  const termStructure = data?.term_structure || []
  const spot = data?.spot || 0
  const expiries = data?.available_expiries || []
  const compareSkew = compareData?.skew || []

  const atmStrike = useMemo(() => {
    if (skew.length === 0) return null
    return skew.reduce((best, pt) =>
      Math.abs(pt.moneyness) < Math.abs(best.moneyness) ? pt : best
    ).strike
  }, [skew])

  // Build chart data based on view
  const chartData = useMemo(() => {
    // Build comparison lookup
    const compareLookup = {}
    for (const pt of compareSkew) {
      compareLookup[pt.strike] = pt
    }

    return skew.map(pt => {
      const row = { strike: pt.strike, moneyness: pt.moneyness }
      const cmp = compareLookup[pt.strike]

      if (view === 'combined') {
        row.vol = pt.vol
        row.put_iv = pt.put_iv
        row.call_iv = pt.call_iv
        if (pt.strike === atmStrike) row.atm = pt.vol
        if (cmp) row.compare_vol = cmp.vol
      } else if (view === 'puts') {
        row.put_iv = pt.raw_put_iv
        if (pt.strike === atmStrike && pt.raw_put_iv) row.atm = pt.raw_put_iv
        if (cmp) row.compare = cmp.raw_put_iv
      } else {
        row.call_iv = pt.raw_call_iv
        if (pt.strike === atmStrike && pt.raw_call_iv) row.atm = pt.raw_call_iv
        if (cmp) row.compare = cmp.raw_call_iv
      }

      return row
    })
  }, [skew, compareSkew, view, atmStrike])

  const viewConfig = {
    combined: {
      lines: [
        { key: 'vol', color: colors.compositeVol, label: 'Composite Vol', width: 2 },
        { key: 'put_iv', color: colors.putIv, label: 'OTM Put', width: 1.5 },
        { key: 'call_iv', color: colors.callIv, label: 'OTM Call', width: 1.5 },
      ],
      compareKey: 'compare_vol',
    },
    puts: {
      lines: [{ key: 'put_iv', color: colors.putIv, label: 'Put IV', width: 2 }],
      compareKey: 'compare',
    },
    calls: {
      lines: [{ key: 'call_iv', color: colors.callIv, label: 'Call IV', width: 2 }],
      compareKey: 'compare',
    },
  }

  const cfg = viewConfig[view]

  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        {/* Header */}
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h3 className="text-white font-semibold">Implied Volatility Skew</h3>
          <div className="flex items-center gap-2">
            {VIEWS.map(v => (
              <button
                key={v.key}
                onClick={() => setView(v.key)}
                className={`px-2 py-1 text-xs rounded ${
                  view === v.key ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'
                }`}
              >
                {v.label}
              </button>
            ))}
            <form onSubmit={handleSubmit} className="flex gap-1 ml-2">
              <input
                type="text"
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                className="w-16 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white text-center font-mono"
              />
              <button type="submit" className="px-2 py-1 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-500">Go</button>
            </form>
          </div>
        </div>

        {/* Expiry selectors */}
        {expiries.length > 0 && (
          <div className="flex items-center gap-3 mb-3 text-xs">
            <label className="text-gray-400">
              Expiry:
              <select
                value={selectedExpiry}
                onChange={e => setSelectedExpiry(e.target.value)}
                className="ml-1 bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-white"
              >
                <option value="">Auto (most liquid)</option>
                {expiries.map(e => <option key={e} value={e}>{e}</option>)}
              </select>
            </label>
            <label className="text-gray-400">
              Compare:
              <select
                value={compareExpiry}
                onChange={e => setCompareExpiry(e.target.value)}
                className="ml-1 bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-white"
              >
                <option value="">None</option>
                {expiries.filter(e => e !== (selectedExpiry || data?.skew_expiry)).map(e => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>
            </label>
          </div>
        )}

        {loading && <p className="text-gray-500 text-sm py-4 text-center">Loading options data...</p>}

        {!loading && chartData.length > 0 && (
          <div>
            <p className="text-xs text-gray-400 mb-2">
              {data.skew_expiry} expiry · spot: ${spot}
              {compareExpiry && ` · comparing with ${compareExpiry}`}
            </p>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="moneyness"
                  tick={{ fill: '#9CA3AF', fontSize: 10 }}
                  tickFormatter={v => `${v > 0 ? '+' : ''}${v}%`}
                  interval={Math.max(0, Math.floor(chartData.length / 10))}
                  label={{ value: 'Moneyness (% from spot)', position: 'insideBottom', offset: -2, fill: '#6B7280', fontSize: 10 }}
                />
                <YAxis
                  tick={{ fill: '#9CA3AF', fontSize: 11 }}
                  tickFormatter={v => `${v}%`}
                  domain={['auto', 'auto']}
                  label={{ value: 'Implied Volatility', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload || !payload[0]) return null
                    const seen = new Set()
                    const items = payload.filter(p => {
                      if (p.value == null || seen.has(p.dataKey)) return false
                      seen.add(p.dataKey)
                      return true
                    })
                    const row = payload[0].payload
                    const names = {
                      vol: 'Composite Vol', put_iv: view === 'combined' ? 'OTM Put IV' : 'Put IV',
                      call_iv: view === 'combined' ? 'OTM Call IV' : 'Call IV',
                      atm: 'ATM', compare: `Compare (${compareExpiry})`,
                      compare_vol: `Compare (${compareExpiry})`,
                    }
                    const isAtm = row.moneyness === 0 || row.strike === atmStrike
                    return (
                      <div style={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
                        <p style={{ color: '#fff', marginBottom: 4 }}>
                          ${row.strike} ({row.moneyness > 0 ? '+' : ''}{row.moneyness}%){isAtm ? ' ATM' : ''}
                        </p>
                        {items.map((p, i) => (
                          <p key={i} style={{ color: p.color || '#9CA3AF', margin: 0 }}>
                            {names[p.dataKey] || p.dataKey}: {p.value?.toFixed(2)}%
                          </p>
                        ))}
                      </div>
                    )
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                  onClick={skewLegend.handleLegendClick}
                  formatter={skewLegend.legendFormatter}
                  payload={[
                    ...cfg.lines.map(l => ({ value: l.label, dataKey: l.key, type: 'line', color: l.color })),
                    ...(compareExpiry ? [{ value: `Compare (${compareExpiry})`, dataKey: cfg.compareKey, type: 'plainline', color: '#F59E0B' }] : []),
                    { value: 'ATM', dataKey: 'atm', type: 'diamond', color: '#F59E0B' },
                  ]}
                />
                <ReferenceLine x={0} stroke="#F59E0B" strokeDasharray="4 4" strokeWidth={1.5}
                  label={{ value: `ATM $${spot.toFixed(0)}`, fill: '#F59E0B', fontSize: 10, position: 'top' }}
                />
                {/* Dashed interpolation lines */}
                {cfg.lines.map(l => (
                  <Line key={`${l.key}-dash`} type="monotone" dataKey={l.key} stroke={l.color}
                    strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.4} dot={false} connectNulls
                    legendType="none" hide={skewLegend.isHidden(l.key)} />
                ))}
                {/* Solid lines */}
                {cfg.lines.map(l => (
                  <Line key={l.key} type="monotone" dataKey={l.key} stroke={l.color}
                    strokeWidth={l.width} dot={false} connectNulls={false}
                    legendType="none" hide={skewLegend.isHidden(l.key)} />
                ))}
                {/* Comparison line */}
                {compareExpiry && (
                  <Line type="monotone" dataKey={cfg.compareKey} stroke="#F59E0B"
                    strokeWidth={1.5} strokeDasharray="6 3" dot={false} connectNulls
                    legendType="none" hide={skewLegend.isHidden(cfg.compareKey)} />
                )}
                {/* ATM marker */}
                <Line type="monotone" dataKey="atm" stroke="none"
                  dot={{ fill: '#F59E0B', stroke: cfg.lines[0].color, strokeWidth: 2, r: 6 }}
                  legendType="none" connectNulls={false} hide={skewLegend.isHidden('atm')} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Term Structure */}
      {!loading && termStructure.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <p className="text-xs text-gray-400 mb-2">ATM Put-Call IV Spread — Term Structure</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={termStructure}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="expiry" tick={{ fill: '#9CA3AF', fontSize: 10 }}
                tickFormatter={v => { const d = new Date(v + 'T00:00:00'); return d.toLocaleDateString('en', { month: 'short', year: 'numeric' }) }} interval={0} angle={-45} textAnchor="end" height={50} />
              <YAxis tick={{ fill: '#9CA3AF', fontSize: 11 }} tickFormatter={v => `${v}pp`} domain={['auto', 'auto']}
                label={{ value: 'IV Spread (pp)', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
              />
              <Tooltip contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }} labelStyle={{ color: '#fff' }}
                formatter={(v, name) => {
                  if (name === 'spread') return [`${v.toFixed(2)}pp`, 'Put-Call Spread']
                  return [`${v.toFixed(2)}%`, name === 'put_iv' ? 'Put IV' : 'Call IV']
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                onClick={termLegend.handleLegendClick}
                formatter={(v, entry) => termLegend.legendFormatter(
                  v === 'spread' ? 'Put-Call Spread' : v === 'put_iv' ? 'Put IV' : 'Call IV',
                  entry
                )}
              />
              <Bar dataKey="put_iv" fill={colors.putIv} opacity={0.6} hide={termLegend.isHidden('put_iv')} />
              <Bar dataKey="call_iv" fill={colors.callIv} opacity={0.6} hide={termLegend.isHidden('call_iv')} />
              <Bar dataKey="spread" fill="#6366F1" hide={termLegend.isHidden('spread')} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && skew.length === 0 && (
        <p className="text-gray-500 text-sm text-center">No options data available for {ticker}</p>
      )}
    </div>
  )
}
