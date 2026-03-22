import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const REGIME_COLORS = ['#22C55E', '#EF4444', '#F59E0B'] // regime 0 (low vol), 1 (high vol), 2

export default function RegimeOverlay({
  ticker,
  regimeData = null,
  loading = false,
  nRegimes = 2,
  source = '',
  onNRegimesChange,
  onSourceChange,
}) {
  const [statsView, setStatsView] = useState('full') // 'full' | 'regime_0' | 'regime_1' | ...

  const regimes = regimeData?.regimes || []
  const stats = regimeData?.stats || []

  // Build chart data — show regime as colored bars over time
  const chartData = regimes.map(r => ({
    date: new Date(r.date + 'T00:00:00').toLocaleDateString('en', { month: 'short', year: 'numeric' }),
    regime: r.regime,
    probability: r.probability,
  }))

  // Stats for selected view
  const displayStats = statsView === 'full'
    ? stats
    : stats.filter(s => `regime_${s.regime}` === statsView)

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold">Regime Detection</h3>
        <div className="flex items-center gap-2 text-xs">
          <label className="text-gray-400">
            Regimes:
            <select value={nRegimes} onChange={e => onNRegimesChange?.(Number(e.target.value))}
              className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </label>
          <label className="text-gray-400">
            Source:
            <select value={source} onChange={e => onSourceChange?.(e.target.value)}
              className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              <option value="">Self ({ticker})</option>
              <option value="SPY">SPY</option>
              <option value="^VIX">VIX</option>
              <option value="QQQ">QQQ</option>
              <option value="IWM">IWM</option>
            </select>
          </label>
        </div>
      </div>

      {regimeData?.source_ticker && regimeData.source_ticker !== ticker && (
        <p className="text-xs text-gray-500">
          Regimes detected from {regimeData.source_ticker}, overlaid onto {ticker}
        </p>
      )}

      {loading && <p className="text-gray-500 text-sm text-center py-4">Fitting Markov model...</p>}

      {/* Regime timeline */}
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={chartData} barCategoryGap={0} barGap={0}>
            <XAxis dataKey="date" tick={{ fill: '#9CA3AF', fontSize: 9 }}
              interval={Math.max(0, Math.floor(chartData.length / 8))} />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#fff' }}
              formatter={(v, name, props) => {
                const r = props.payload.regime
                return [`Regime ${r} (${(props.payload.probability * 100).toFixed(0)}%)`, 'State']
              }}
            />
            <Bar dataKey="probability">
              {chartData.map((entry, i) => (
                <Cell key={i} fill={REGIME_COLORS[entry.regime % REGIME_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      {/* Regime legend */}
      {stats.length > 0 && (
        <div className="flex items-center gap-2">
          {stats.map(s => (
            <span key={s.regime} className="flex items-center gap-1 text-xs text-gray-300">
              <span className="inline-block w-3 h-3 rounded"
                style={{ backgroundColor: REGIME_COLORS[s.regime % REGIME_COLORS.length] }} />
              Regime {s.regime}: {s.volatility}% vol
            </span>
          ))}
        </div>
      )}

      {/* Stats table with regime toggle */}
      {stats.length > 0 && (
        <div>
          <div className="flex gap-1 mb-2">
            <button onClick={() => setStatsView('full')}
              className={`px-2 py-0.5 text-xs rounded ${statsView === 'full' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}>
              Full History
            </button>
            {stats.map(s => (
              <button key={s.regime} onClick={() => setStatsView(`regime_${s.regime}`)}
                className={`px-2 py-0.5 text-xs rounded ${statsView === `regime_${s.regime}` ? 'text-white' : 'text-gray-400'}`}
                style={statsView === `regime_${s.regime}`
                  ? { backgroundColor: REGIME_COLORS[s.regime % REGIME_COLORS.length] }
                  : { backgroundColor: '#374151' }
                }>
                Regime {s.regime}
              </button>
            ))}
          </div>

          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-gray-500">
                <th className="text-left px-2 py-1">Regime</th>
                <th className="text-right px-2 py-1">Ann. Return</th>
                <th className="text-right px-2 py-1">Ann. Vol</th>
                <th className="text-right px-2 py-1">Days</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700/50">
              {displayStats.map(s => (
                <tr key={s.regime}>
                  <td className="px-2 py-1 text-white flex items-center gap-1">
                    <span className="inline-block w-2 h-2 rounded"
                      style={{ backgroundColor: REGIME_COLORS[s.regime % REGIME_COLORS.length] }} />
                    Regime {s.regime}
                  </td>
                  <td className={`px-2 py-1 text-right ${s.mean_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {s.mean_return >= 0 ? '+' : ''}{s.mean_return}%
                  </td>
                  <td className="px-2 py-1 text-right text-white">{s.volatility}%</td>
                  <td className="px-2 py-1 text-right text-gray-400">{s.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && regimes.length === 0 && (
        <p className="text-gray-500 text-sm text-center">Not enough data for regime detection</p>
      )}
    </div>
  )
}
