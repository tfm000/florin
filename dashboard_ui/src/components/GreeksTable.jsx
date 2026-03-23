import { useMemo } from 'react'
import { allGreeks } from '../utils/blackscholes'
import { useChartColors } from '../hooks/useChartColors'

/**
 * Greeks calculator and display table.
 *
 * Takes options chain data (from IV spread endpoint) and computes
 * Black-Scholes Greeks for each strike.
 */
export default function GreeksTable({ skew, spot, expiry, riskFreeRate = 0.045 }) {
  const colors = useChartColors()

  // Compute time to expiry in years
  const T = useMemo(() => {
    if (!expiry) return 0
    const now = new Date()
    const exp = new Date(expiry + 'T16:00:00') // market close
    const diffMs = exp - now
    return Math.max(diffMs / (365.25 * 24 * 60 * 60 * 1000), 0.001)
  }, [expiry])

  // Compute Greeks for each strike that has IV data
  const rows = useMemo(() => {
    if (!skew || !spot || spot <= 0) return []

    return skew
      .filter(pt => pt.raw_call_iv || pt.raw_put_iv)
      .map(pt => {
        const K = pt.strike
        const callIV = pt.raw_call_iv ? pt.raw_call_iv / 100 : null
        const putIV = pt.raw_put_iv ? pt.raw_put_iv / 100 : null

        const callGreeks = callIV ? allGreeks(spot, K, T, riskFreeRate, callIV, 'call') : null
        const putGreeks = putIV ? allGreeks(spot, K, T, riskFreeRate, putIV, 'put') : null

        return { strike: K, moneyness: pt.moneyness, callGreeks, putGreeks, callIV, putIV }
      })
  }, [skew, spot, T, riskFreeRate])

  if (rows.length === 0) return null

  const fmt = (v, dp = 4) => v != null ? v.toFixed(dp) : '—'

  // Semantic colors for Greeks:
  // Delta = positive (directional exposure)
  // Theta = negative (time decay cost)
  // Vega = series color (volatility sensitivity)
  const deltaColor = colors.positive
  const thetaColor = colors.negative
  const vegaColor = colors.series[1] // indigo/teal

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Options Greeks</h3>
        <span className="text-xs text-gray-500">
          T={T.toFixed(4)}y · r={riskFreeRate * 100}% · {expiry}
        </span>
      </div>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full text-xs font-mono">
          <thead className="bg-gray-750 sticky top-0">
            <tr className="text-gray-400">
              <th className="px-2 py-1 text-right">Strike</th>
              <th className="px-2 py-1 text-right">Mny%</th>
              <th className="px-1 py-1 text-center text-gray-500" colSpan={6}>— CALL —</th>
              <th className="px-1 py-1 text-center text-gray-500" colSpan={6}>— PUT —</th>
            </tr>
            <tr className="text-gray-500">
              <th></th><th></th>
              <th className="px-2 py-1 text-right">IV</th>
              <th className="px-2 py-1 text-right">Price</th>
              <th className="px-2 py-1 text-right">Delta</th>
              <th className="px-2 py-1 text-right">Gamma</th>
              <th className="px-2 py-1 text-right">Vega</th>
              <th className="px-2 py-1 text-right">Theta</th>
              <th className="px-2 py-1 text-right">IV</th>
              <th className="px-2 py-1 text-right">Price</th>
              <th className="px-2 py-1 text-right">Delta</th>
              <th className="px-2 py-1 text-right">Gamma</th>
              <th className="px-2 py-1 text-right">Vega</th>
              <th className="px-2 py-1 text-right">Theta</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700/50">
            {rows.map(r => {
              const isATM = Math.abs(r.moneyness) < 1
              return (
                <tr key={r.strike} className={`hover:bg-gray-700/30 ${isATM ? 'bg-yellow-900/10' : ''}`}>
                  <td className="px-2 py-0.5 text-right text-white">${r.strike}</td>
                  <td className="px-2 py-0.5 text-right text-gray-400">{r.moneyness > 0 ? '+' : ''}{r.moneyness.toFixed(1)}</td>
                  {/* Call Greeks */}
                  <td className="px-2 py-0.5 text-right text-gray-400">{r.callIV ? (r.callIV * 100).toFixed(1) + '%' : '—'}</td>
                  <td className="px-2 py-0.5 text-right text-white">{fmt(r.callGreeks?.price, 2)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: deltaColor }}>{fmt(r.callGreeks?.delta)}</td>
                  <td className="px-2 py-0.5 text-right text-gray-300">{fmt(r.callGreeks?.gamma)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: vegaColor }}>{fmt(r.callGreeks?.vega)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: thetaColor }}>{fmt(r.callGreeks?.theta)}</td>
                  {/* Put Greeks */}
                  <td className="px-2 py-0.5 text-right text-gray-400">{r.putIV ? (r.putIV * 100).toFixed(1) + '%' : '—'}</td>
                  <td className="px-2 py-0.5 text-right text-white">{fmt(r.putGreeks?.price, 2)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: deltaColor }}>{fmt(r.putGreeks?.delta)}</td>
                  <td className="px-2 py-0.5 text-right text-gray-300">{fmt(r.putGreeks?.gamma)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: vegaColor }}>{fmt(r.putGreeks?.vega)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: thetaColor }}>{fmt(r.putGreeks?.theta)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
