import { useMemo } from 'react'
import { allGreeks } from '../utils/blackscholes'
import { useChartColors } from '../hooks/useChartColors'

/**
 * Black-Scholes Greeks table.
 *
 * The IV used for both put and call Greeks at a given strike is the
 * hybrid (parametric + GP-residual mean) implied vol from the new
 * options-surface pipeline. Under put-call parity the implied IV is
 * identical for both legs at the same strike, so we feed the same
 * ``iv_hybrid`` into both ``allGreeks(.., 'call')`` and ``allGreeks(.., 'put')``.
 *
 * @param {Array<{strike, iv_hybrid, moneyness}>} ivCurve  hybrid IV per strike (decimal)
 * @param {number} spot     underlying spot
 * @param {string} expiry   YYYY-MM-DD
 * @param {number} riskFreeRate  annualised SOFR, decimal (e.g. 0.045 = 4.5%)
 */
export default function GreeksTable({
  ivCurve,
  spot,
  expiry,
  riskFreeRate = 0.045,
}) {
  const colors = useChartColors()

  const T = useMemo(() => {
    if (!expiry) return 0
    const now = new Date()
    const exp = new Date(expiry + 'T16:00:00')
    const diffMs = exp - now
    return Math.max(diffMs / (365.25 * 24 * 60 * 60 * 1000), 0.001)
  }, [expiry])

  const rows = useMemo(() => {
    if (!ivCurve || !spot || spot <= 0) return []
    // Sample the curve at ~25 strikes around spot to keep the table readable.
    const filtered = ivCurve.filter(p => p.iv_hybrid > 0)
    if (filtered.length === 0) return []
    const step = Math.max(1, Math.floor(filtered.length / 25))
    return filtered
      .filter((_, i) => i % step === 0)
      .map(p => {
        const K = p.strike
        const sigma = p.iv_hybrid
        // Same hybrid IV for both legs — see module docstring.
        const callGreeks = allGreeks(spot, K, T, riskFreeRate, sigma, 'call')
        const putGreeks = allGreeks(spot, K, T, riskFreeRate, sigma, 'put')
        const moneynessPct = ((K / spot) - 1) * 100
        return { strike: K, moneyness: moneynessPct, iv: sigma, callGreeks, putGreeks }
      })
  }, [ivCurve, spot, T, riskFreeRate])

  if (rows.length === 0) return null

  const fmt = (v, dp = 4) => (v != null ? v.toFixed(dp) : '—')
  const deltaColor = colors.positive
  const thetaColor = colors.negative
  const vegaColor = colors.series[1]

  const rateLabel = `SOFR ${(riskFreeRate * 100).toFixed(2)}%`

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Options Greeks</h3>
        <span className="text-xs text-gray-500">
          T={T.toFixed(4)}y · r={rateLabel} · {expiry}
        </span>
      </div>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full text-xs font-mono">
          <thead className="bg-gray-750 sticky top-0">
            <tr className="text-gray-400">
              <th className="px-2 py-1 text-right">Strike</th>
              <th className="px-2 py-1 text-right">Mny%</th>
              <th className="px-2 py-1 text-right">IV</th>
              <th className="px-1 py-1 text-center text-gray-500" colSpan={5}>— CALL —</th>
              <th className="px-1 py-1 text-center text-gray-500" colSpan={5}>— PUT —</th>
            </tr>
            <tr className="text-gray-500">
              <th></th>
              <th></th>
              <th></th>
              <th className="px-2 py-1 text-right">Price</th>
              <th className="px-2 py-1 text-right">Delta</th>
              <th className="px-2 py-1 text-right">Gamma</th>
              <th className="px-2 py-1 text-right">Vega</th>
              <th className="px-2 py-1 text-right">Theta</th>
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
                <tr
                  key={r.strike}
                  className={`hover:bg-gray-700/30 ${isATM ? 'bg-yellow-900/10' : ''}`}
                >
                  <td className="px-2 py-0.5 text-right text-white">${r.strike.toFixed(2)}</td>
                  <td className="px-2 py-0.5 text-right text-gray-400">
                    {r.moneyness > 0 ? '+' : ''}
                    {r.moneyness.toFixed(1)}
                  </td>
                  <td className="px-2 py-0.5 text-right text-gray-400">
                    {(r.iv * 100).toFixed(1)}%
                  </td>
                  <td className="px-2 py-0.5 text-right text-white">{fmt(r.callGreeks.price, 2)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: deltaColor }}>
                    {fmt(r.callGreeks.delta)}
                  </td>
                  <td className="px-2 py-0.5 text-right text-gray-300">
                    {fmt(r.callGreeks.gamma)}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: vegaColor }}>
                    {fmt(r.callGreeks.vega)}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: thetaColor }}>
                    {fmt(r.callGreeks.theta)}
                  </td>
                  <td className="px-2 py-0.5 text-right text-white">{fmt(r.putGreeks.price, 2)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: deltaColor }}>
                    {fmt(r.putGreeks.delta)}
                  </td>
                  <td className="px-2 py-0.5 text-right text-gray-300">
                    {fmt(r.putGreeks.gamma)}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: vegaColor }}>
                    {fmt(r.putGreeks.vega)}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: thetaColor }}>
                    {fmt(r.putGreeks.theta)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
