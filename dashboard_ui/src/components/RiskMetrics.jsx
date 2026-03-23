import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'
import { valueColor } from '../utils/colors'

export default function RiskMetrics({ ticker, period = '1y', customStart = '', customEnd = '' }) {
  const colors = useChartColors()
  const queryStr = customStart && customEnd
    ? `period=${period}&start=${customStart}&end=${customEnd}`
    : `period=${period}`

  const { data, loading } = useApi(`/risk/${ticker}?${queryStr}`)

  if (loading) return <p className="text-gray-500 text-sm py-2">Computing risk metrics...</p>
  if (!data || data.trading_days === 0) return null

  const fmt = (v) => v != null ? `${v.toFixed(2)}%` : '—'

  const ratioColor = (v) => v != null ? valueColor(v, colors) : colors.neutral

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Risk Metrics</h3>
        <span className="text-xs text-gray-500">
          {data.trading_days} days · r_f={data.risk_free_rate}%
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-gray-500">
              <th className="text-left px-2 py-1">Measure</th>
              <th className="text-right px-2 py-1">Historical</th>
              {data.parametric && <th className="text-right px-2 py-1">Parametric (t-dist)</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700/50">
            <tr>
              <td className="px-2 py-1 text-gray-400">Ann. Return</td>
              <td className="px-2 py-1 text-right" style={{ color: valueColor(data.annualized_return, colors) }}>{fmt(data.annualized_return)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: ratioColor(data.parametric_return) }}>{data.parametric_return != null ? fmt(data.parametric_return) : '—'}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">Ann. Volatility</td>
              <td className="px-2 py-1 text-right text-white">{data.annualized_vol}%</td>
              {data.parametric && <td className="px-2 py-1 text-right text-white">{data.parametric_vol != null ? `${data.parametric_vol}%` : '—'}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">Sharpe</td>
              <td className="px-2 py-1 text-right" style={{ color: ratioColor(data.sharpe) }}>{data.sharpe.toFixed(2)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: ratioColor(data.parametric_sharpe) }}>{data.parametric_sharpe != null ? data.parametric_sharpe.toFixed(2) : '—'}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">Sortino</td>
              <td className="px-2 py-1 text-right" style={{ color: ratioColor(data.sortino) }}>{data.sortino.toFixed(2)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: ratioColor(data.parametric_sortino) }}>{data.parametric_sortino != null ? data.parametric_sortino.toFixed(2) : '—'}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">VaR (95%)</td>
              <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.historical.var_95)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.parametric.var_95)}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">VaR (99%)</td>
              <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.historical.var_99)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.parametric.var_99)}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">CVaR (95%)</td>
              <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.historical.cvar_95)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.parametric.cvar_95)}</td>}
            </tr>
            <tr>
              <td className="px-2 py-1 text-gray-400">CVaR (99%)</td>
              <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.historical.cvar_99)}</td>
              {data.parametric && <td className="px-2 py-1 text-right" style={{ color: colors.negative }}>{fmt(data.parametric.cvar_99)}</td>}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
