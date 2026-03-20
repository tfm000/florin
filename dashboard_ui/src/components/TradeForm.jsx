import { useState } from 'react'
import { apiPost } from '../hooks/useApi'

export default function TradeForm({ onComplete }) {
  const [ticker, setTicker] = useState('')
  const [side, setSide] = useState('buy')
  const [quantity, setQuantity] = useState('')
  const [targetValue, setTargetValue] = useState('')
  const [limitPrice, setLimitPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      let endpoint, body

      if (stopPrice) {
        endpoint = '/orders/stoploss'
        body = { ticker, quantity: parseFloat(quantity), stop_price: parseFloat(stopPrice) }
      } else if (side === 'buy') {
        endpoint = '/orders/buy'
        body = {
          ticker,
          quantity: quantity ? parseFloat(quantity) : null,
          target_value: targetValue ? parseFloat(targetValue) : null,
          limit_price: limitPrice ? parseFloat(limitPrice) : null,
        }
      } else {
        endpoint = '/orders/sell'
        body = {
          ticker,
          quantity: quantity ? parseFloat(quantity) : null,
          limit_price: limitPrice ? parseFloat(limitPrice) : null,
        }
      }

      const result = await apiPost(endpoint, body)
      setSuccess(`Order placed: ${result.order_id}`)
      onComplete?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
      <h3 className="text-white font-bold">Place Order</h3>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setSide('buy')}
          className={`flex-1 py-2 rounded text-sm font-bold ${side === 'buy' ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-400'}`}
        >
          BUY
        </button>
        <button
          type="button"
          onClick={() => setSide('sell')}
          className={`flex-1 py-2 rounded text-sm font-bold ${side === 'sell' ? 'bg-red-600 text-white' : 'bg-gray-700 text-gray-400'}`}
        >
          SELL
        </button>
      </div>

      <input
        type="text"
        placeholder="Ticker (e.g. AAPL)"
        value={ticker}
        onChange={e => setTicker(e.target.value.toUpperCase())}
        required
        className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
      />

      <div className="grid grid-cols-2 gap-2">
        <input
          type="number"
          placeholder="Quantity"
          value={quantity}
          onChange={e => setQuantity(e.target.value)}
          step="any"
          className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
        />
        {side === 'buy' && (
          <input
            type="number"
            placeholder="Target value ($)"
            value={targetValue}
            onChange={e => setTargetValue(e.target.value)}
            step="any"
            className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
          />
        )}
        <input
          type="number"
          placeholder="Limit price"
          value={limitPrice}
          onChange={e => setLimitPrice(e.target.value)}
          step="any"
          className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
        />
        <input
          type="number"
          placeholder="Stop price"
          value={stopPrice}
          onChange={e => setStopPrice(e.target.value)}
          step="any"
          className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"
        />
      </div>

      <button
        type="submit"
        disabled={loading || !ticker}
        className={`w-full py-2 rounded font-bold text-sm ${
          side === 'buy'
            ? 'bg-green-600 hover:bg-green-700 text-white'
            : 'bg-red-600 hover:bg-red-700 text-white'
        } disabled:opacity-50`}
      >
        {loading ? 'Placing...' : `${side.toUpperCase()} ${ticker || '...'}`}
      </button>

      {error && <p className="text-red-400 text-xs">{error}</p>}
      {success && <p className="text-green-400 text-xs">{success}</p>}
    </form>
  )
}
