import { useState, useCallback } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'

export default function BrokerTab() {
  const { info, ticker } = useOutletContext()

  // Order form state
  const [side, setSide] = useState('buy')
  const [orderType, setOrderType] = useState('market')
  const [quantity, setQuantity] = useState('')
  const [targetValue, setTargetValue] = useState('')
  const [limitPrice, setLimitPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // Refresh key to re-fetch position & orders after trade
  const [refreshKey, setRefreshKey] = useState(0)
  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])

  // Current position for this ticker
  const { data: position } = useApi(`/positions/${ticker}`, {
    autoFetch: true,
    refreshKey,
    onError: () => null, // 404 is expected if no position
  })

  // All pending orders (filter to this ticker)
  const { data: allPending } = useApi('/orders/pending', { refreshKey })
  const pendingOrders = (allPending || []).filter(
    o => o.ticker?.toUpperCase() === ticker.toUpperCase()
  )

  // Trade history for this ticker
  const { data: trades } = useApi(`/trades?ticker=${ticker}&limit=20`, { refreshKey })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      let endpoint, body

      if (orderType === 'stop') {
        endpoint = '/orders/stoploss'
        body = { ticker, quantity: parseFloat(quantity), stop_price: parseFloat(stopPrice) }
      } else if (side === 'buy') {
        endpoint = '/orders/buy'
        body = {
          ticker,
          quantity: quantity ? parseFloat(quantity) : null,
          target_value: targetValue ? parseFloat(targetValue) : null,
          limit_price: orderType === 'limit' ? parseFloat(limitPrice) : null,
        }
      } else {
        endpoint = '/orders/sell'
        body = {
          ticker,
          quantity: quantity ? parseFloat(quantity) : null,
          limit_price: orderType === 'limit' ? parseFloat(limitPrice) : null,
        }
      }

      const result = await apiPost(endpoint, body)
      setSuccess(`Order ${result.status}: ${result.side} ${result.filled_quantity || quantity} ${ticker}${result.filled_price ? ` @ $${result.filled_price.toFixed(2)}` : ''}`)
      setQuantity('')
      setTargetValue('')
      setLimitPrice('')
      setStopPrice('')
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async (orderId) => {
    try {
      await fetch(`/api/orders/${orderId}`, { method: 'DELETE' })
      refresh()
    } catch (err) {
      setError(`Cancel failed: ${err.message}`)
    }
  }

  const spot = info?.current_price

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Order Form */}
        <div className="lg:col-span-2">
          <form onSubmit={handleSubmit} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-white font-bold">Place Order — {ticker}</h3>
              {spot && (
                <span className="text-white font-mono text-lg">${spot.toFixed(2)}</span>
              )}
            </div>

            {/* Buy / Sell toggle */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setSide('buy'); if (orderType === 'stop') setOrderType('market') }}
                className={`flex-1 py-2.5 rounded text-sm font-bold transition ${
                  side === 'buy' ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-gray-300'
                }`}
              >
                BUY
              </button>
              <button
                type="button"
                onClick={() => setSide('sell')}
                className={`flex-1 py-2.5 rounded text-sm font-bold transition ${
                  side === 'sell' ? 'bg-red-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-gray-300'
                }`}
              >
                SELL
              </button>
            </div>

            {/* Order type selector */}
            <div className="flex gap-1 bg-gray-900/50 rounded-lg p-0.5">
              {['market', 'limit', 'stop'].map(type => (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    setOrderType(type)
                    if (type === 'stop') setSide('sell')
                  }}
                  className={`flex-1 px-3 py-1.5 rounded text-xs font-medium transition ${
                    orderType === type
                      ? 'bg-gray-700 text-white'
                      : 'text-gray-400 hover:text-gray-300'
                  }`}
                >
                  {type === 'market' ? 'Market' : type === 'limit' ? 'Limit' : 'Stop Loss'}
                </button>
              ))}
            </div>

            {/* Order inputs */}
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-gray-400 text-xs uppercase block mb-1">Quantity</label>
                  <input
                    type="number"
                    placeholder="Shares"
                    value={quantity}
                    onChange={e => setQuantity(e.target.value)}
                    step="any"
                    min="0"
                    required={orderType === 'stop' || !targetValue}
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
                  />
                </div>
                {side === 'buy' && orderType !== 'stop' && (
                  <div>
                    <label className="text-gray-400 text-xs uppercase block mb-1">Or Target Value</label>
                    <input
                      type="number"
                      placeholder="$ amount"
                      value={targetValue}
                      onChange={e => setTargetValue(e.target.value)}
                      step="any"
                      min="0"
                      className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
                    />
                  </div>
                )}
              </div>

              {orderType === 'limit' && (
                <div>
                  <label className="text-gray-400 text-xs uppercase block mb-1">Limit Price</label>
                  <input
                    type="number"
                    placeholder={spot ? `Current: $${spot.toFixed(2)}` : 'Price per share'}
                    value={limitPrice}
                    onChange={e => setLimitPrice(e.target.value)}
                    step="any"
                    min="0"
                    required
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
                  />
                </div>
              )}

              {orderType === 'stop' && (
                <div>
                  <label className="text-gray-400 text-xs uppercase block mb-1">Stop Price</label>
                  <input
                    type="number"
                    placeholder={spot ? `Current: $${spot.toFixed(2)}` : 'Trigger price'}
                    value={stopPrice}
                    onChange={e => setStopPrice(e.target.value)}
                    step="any"
                    min="0"
                    required
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
                  />
                </div>
              )}

              {/* Estimated value */}
              {quantity && spot && orderType !== 'stop' && (
                <p className="text-gray-500 text-xs">
                  Est. value: ${(parseFloat(quantity) * spot).toFixed(2)}
                  {orderType === 'limit' && limitPrice && (
                    <> · at limit: ${(parseFloat(quantity) * parseFloat(limitPrice)).toFixed(2)}</>
                  )}
                </p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || (!quantity && !targetValue)}
              className={`w-full py-2.5 rounded font-bold text-sm transition ${
                side === 'buy'
                  ? 'bg-green-600 hover:bg-green-500 text-white'
                  : 'bg-red-600 hover:bg-red-500 text-white'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {loading
                ? 'Placing order...'
                : orderType === 'stop'
                  ? `SET STOP LOSS — ${ticker}`
                  : `${side.toUpperCase()} ${orderType === 'limit' ? '(LIMIT)' : '(MARKET)'} — ${ticker}`
              }
            </button>

            {error && (
              <div className="bg-red-900/30 border border-red-700/50 rounded p-2">
                <p className="text-red-400 text-xs">{error}</p>
              </div>
            )}
            {success && (
              <div className="bg-green-900/30 border border-green-700/50 rounded p-2">
                <p className="text-green-400 text-xs">{success}</p>
              </div>
            )}
          </form>
        </div>

        {/* Position panel */}
        <div className="space-y-4">
          {/* Current position */}
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <h3 className="text-white font-semibold text-sm mb-3">Position — {ticker}</h3>
            {position && position.quantity > 0 ? (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Shares</span>
                  <span className="text-white font-mono">{position.quantity}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Avg Price</span>
                  <span className="text-white font-mono">${position.avg_price?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Market Value</span>
                  <span className="text-white font-mono">${position.market_value?.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Unrealised P&L</span>
                  <span className={`font-mono font-semibold ${
                    position.unrealised_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {position.unrealised_pnl >= 0 ? '+' : ''}${position.unrealised_pnl?.toFixed(2)}
                    {position.unrealised_pnl_pct != null && (
                      <span className="text-xs ml-1">
                        ({position.unrealised_pnl_pct >= 0 ? '+' : ''}{position.unrealised_pnl_pct?.toFixed(1)}%)
                      </span>
                    )}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-gray-500 text-sm">No open position</p>
            )}
          </div>

          {/* Pending orders for this ticker */}
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <h3 className="text-white font-semibold text-sm mb-3">Pending Orders</h3>
            {pendingOrders.length > 0 ? (
              <div className="space-y-2">
                {pendingOrders.map((order, i) => (
                  <div key={order.order_id || i} className="flex items-center justify-between bg-gray-900/50 rounded p-2">
                    <div className="text-xs">
                      <span className={`font-bold ${order.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                        {order.side}
                      </span>
                      <span className="text-gray-400 ml-1">{order.quantity} @ </span>
                      <span className="text-white font-mono">
                        ${order.limit_price?.toFixed(2) || order.stop_price?.toFixed(2) || 'MKT'}
                      </span>
                      <span className="text-gray-500 ml-1">({order.order_type})</span>
                    </div>
                    <button
                      onClick={() => handleCancel(order.order_id)}
                      className="text-red-400 hover:text-red-300 text-xs px-2 py-0.5 rounded hover:bg-red-900/30"
                    >
                      Cancel
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-500 text-sm">No pending orders</p>
            )}
          </div>
        </div>
      </div>

      {/* Recent trades for this ticker */}
      {trades && trades.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-semibold text-sm mb-3">Recent Trades — {ticker}</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-900/50">
                <tr className="text-gray-400">
                  <th className="px-3 py-2 text-left">Date</th>
                  <th className="px-3 py-2 text-left">Side</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-right">Qty</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Value</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {trades.map((t, i) => (
                  <tr key={t.id || i} className="hover:bg-gray-700/30">
                    <td className="px-3 py-1.5 text-gray-400 font-mono">
                      {t.executed_at ? new Date(t.executed_at).toLocaleDateString() : '—'}
                    </td>
                    <td className={`px-3 py-1.5 font-bold ${t.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                      {t.side}
                    </td>
                    <td className="px-3 py-1.5 text-gray-400">{t.order_type}</td>
                    <td className="px-3 py-1.5 text-right text-white font-mono">{t.quantity}</td>
                    <td className="px-3 py-1.5 text-right text-white font-mono">${t.price?.toFixed(2)}</td>
                    <td className="px-3 py-1.5 text-right text-gray-300 font-mono">${t.total_value?.toFixed(2)}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${
                      t.realised_pnl > 0 ? 'text-green-400' : t.realised_pnl < 0 ? 'text-red-400' : 'text-gray-500'
                    }`}>
                      {t.is_closing_trade && t.realised_pnl != null
                        ? `${t.realised_pnl >= 0 ? '+' : ''}$${t.realised_pnl.toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
