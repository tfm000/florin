import { useState, useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { computePayoff, spotRange, STRATEGIES, bsPrice } from '../utils/blackscholes'
import { useChartColors } from '../hooks/useChartColors'

const STRATEGY_OPTIONS = [
  { key: 'longCall', label: 'Long Call' },
  { key: 'longPut', label: 'Long Put' },
  { key: 'shortCall', label: 'Short Call' },
  { key: 'shortPut', label: 'Short Put' },
  { key: 'straddle', label: 'Straddle' },
  { key: 'bullCallSpread', label: 'Bull Call Spread' },
  { key: 'bearPutSpread', label: 'Bear Put Spread' },
]

export default function PayoffDiagram({ spot, riskFreeRate = 0.045 }) {
  const colors = useChartColors()
  const [strategy, setStrategy] = useState('longCall')
  const [strike, setStrike] = useState(Math.round(spot || 100))
  const [strike2, setStrike2] = useState(Math.round((spot || 100) * 1.05))
  const [iv, setIv] = useState(30) // as %

  const needsSecondStrike = strategy === 'bullCallSpread' || strategy === 'bearPutSpread'

  const payoffData = useMemo(() => {
    if (!spot || spot <= 0) return []
    const sigma = iv / 100
    const T = 30 / 365 // assume 30 DTE for premium estimation
    const range = spotRange(spot, 0.25, 80)

    let positions
    switch (strategy) {
      case 'longCall': {
        const prem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'call')
        positions = STRATEGIES.longCall(strike, prem)
        break
      }
      case 'longPut': {
        const prem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'put')
        positions = STRATEGIES.longPut(strike, prem)
        break
      }
      case 'shortCall': {
        const prem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'call')
        positions = STRATEGIES.shortCall(strike, prem)
        break
      }
      case 'shortPut': {
        const prem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'put')
        positions = STRATEGIES.shortPut(strike, prem)
        break
      }
      case 'straddle': {
        const callPrem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'call')
        const putPrem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'put')
        positions = STRATEGIES.straddle(strike, callPrem, putPrem)
        break
      }
      case 'bullCallSpread': {
        const lowPrem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'call')
        const highPrem = bsPrice(spot, strike2, T, riskFreeRate, sigma, 'call')
        positions = STRATEGIES.bullCallSpread(strike, strike2, lowPrem, highPrem)
        break
      }
      case 'bearPutSpread': {
        const lowPrem = bsPrice(spot, strike, T, riskFreeRate, sigma, 'put')
        const highPrem = bsPrice(spot, strike2, T, riskFreeRate, sigma, 'put')
        positions = STRATEGIES.bearPutSpread(strike, strike2, lowPrem, highPrem)
        break
      }
      default:
        return []
    }

    return computePayoff(positions, range)
  }, [spot, strike, strike2, iv, strategy, riskFreeRate])

  if (!spot) return null

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">Payoff at Expiry</h3>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 mb-3 text-xs">
        <label className="text-gray-400">
          Strategy:
          <select value={strategy} onChange={e => setStrategy(e.target.value)}
            className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
            {STRATEGY_OPTIONS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
        <label className="text-gray-400">
          Strike:
          <input type="number" value={strike} onChange={e => setStrike(Number(e.target.value))}
            step={1} className="ml-1 w-20 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" />
        </label>
        {needsSecondStrike && (
          <label className="text-gray-400">
            Strike 2:
            <input type="number" value={strike2} onChange={e => setStrike2(Number(e.target.value))}
              step={1} className="ml-1 w-20 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" />
          </label>
        )}
        <label className="text-gray-400">
          IV:
          <input type="number" value={iv} onChange={e => setIv(Number(e.target.value))}
            step={1} min={1} max={200}
            className="ml-1 w-16 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" />%
        </label>
      </div>

      {payoffData.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={payoffData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="spot" tick={{ fill: '#9CA3AF', fontSize: 10 }}
              tickFormatter={v => `$${v}`}
              interval={Math.max(0, Math.floor(payoffData.length / 8))}
              label={{ value: 'Spot Price at Expiry', position: 'insideBottom', offset: -2, fill: '#6B7280', fontSize: 10 }}
            />
            <YAxis tick={{ fill: '#9CA3AF', fontSize: 10 }}
              tickFormatter={v => `$${v.toFixed(0)}`}
              label={{ value: 'P&L', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
            />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              formatter={(v) => [`$${v.toFixed(2)}`, 'P&L']}
              labelFormatter={v => `Spot: $${v}`}
            />
            <ReferenceLine y={0} stroke="#6B7280" />
            <ReferenceLine x={spot} stroke="#F59E0B" strokeDasharray="4 4"
              label={{ value: `Spot $${spot}`, fill: '#F59E0B', fontSize: 9, position: 'top' }} />
            <Line type="monotone" dataKey="payoff" stroke={colors.series[0]} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
