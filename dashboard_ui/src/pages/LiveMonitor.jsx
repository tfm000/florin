import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, apiDelete } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'

export default function LiveMonitor() {
  const navigate = useNavigate()
  const { data, loading, refetch } = useApi('/monitor')
  const [livePrices, setLivePrices] = useState({})
  const items = data?.items || []

  const handleMessage = useCallback((msg) => {
    if (msg.channel === 'prices' && msg.data?.payload) {
      const p = msg.data.payload
      if (p.ticker) {
        setLivePrices(prev => ({ ...prev, [p.ticker]: p }))
      }
    }
  }, [])

  const { connected } = useWebSocket(handleMessage)

  const handleRemove = async (e, ticker) => {
    e.stopPropagation()
    try {
      await apiDelete(`/monitor/${ticker}`)
      refetch()
    } catch { /* ignore */ }
  }

  const getStatusDot = (item) => {
    const live = livePrices[item.ticker]
    if (live) return 'bg-green-500'
    if (item.current_price) return 'bg-yellow-500'
    return 'bg-gray-500'
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-gray-300">Live Monitor</h2>
          <span className={`text-xs px-2 py-1 rounded ${connected ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'}`}>
            {connected ? 'LIVE' : 'DISCONNECTED'}
          </span>
        </div>
        {data && <span className="text-gray-400 text-sm">{data.total} assets</span>}
      </div>

      {loading && <p className="text-gray-500">Loading monitored assets...</p>}

      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-2">No assets being monitored</p>
          <button
            onClick={() => navigate('/research')}
            className="text-indigo-400 hover:text-indigo-300 text-sm underline"
          >
            Search for assets to monitor
          </button>
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-3 py-2 w-4"></th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Ticker</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Name</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Price</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Change %</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Volume</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {items.map(item => {
                const live = livePrices[item.ticker]
                const price = live?.price || item.current_price
                const changePct = live?.change_pct || item.change_pct
                const volume = live?.volume || item.volume

                return (
                  <tr
                    key={item.ticker}
                    onClick={() => navigate(`/monitoring/live/${item.ticker}`)}
                    className="hover:bg-gray-800/50 cursor-pointer"
                  >
                    <td className="px-3 py-2">
                      <span className={`inline-block w-2 h-2 rounded-full ${getStatusDot(item)}`} />
                    </td>
                    <td className="px-3 py-2 font-mono text-white font-semibold">{item.ticker}</td>
                    <td className="px-3 py-2 text-gray-300 truncate max-w-48">{item.name}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {price != null ? `$${price.toFixed(2)}` : '—'}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${changePct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {changePct != null ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%` : '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-400">
                      {volume != null ? volume.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={(e) => handleRemove(e, item.ticker)}
                        className="text-red-500 hover:text-red-400 text-xs"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
