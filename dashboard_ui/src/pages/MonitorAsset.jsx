import { useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'
import { useChartColors } from '../hooks/useChartColors'

export default function MonitorAsset() {
  const { ticker } = useParams()
  const colors = useChartColors()
  const { data: info } = useApi(`/research/asset/${ticker}`)
  const [liveQuote, setLiveQuote] = useState(null)
  const [ticks, setTicks] = useState([])

  const handleMessage = useCallback((msg) => {
    if (msg.channel === 'prices' && msg.data?.payload) {
      const p = msg.data.payload
      if (p.ticker === ticker) {
        setLiveQuote(p)
        setTicks(prev => [...prev, {
          time: new Date().toLocaleTimeString(),
          price: p.price,
          volume: p.volume,
        }].slice(-200))
      }
    }
  }, [ticker])

  const { connected } = useWebSocket(handleMessage)

  const price = liveQuote?.price || info?.current_price
  const prevClose = liveQuote?.prev_close || info?.previous_close
  const changePct = price && prevClose ? ((price - prevClose) / prevClose) * 100 : 0
  const open = liveQuote?.open_price
  const high = liveQuote?.high
  const low = liveQuote?.low
  const volume = liveQuote?.volume

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Link to="/monitor" className="text-gray-400 hover:text-white text-sm">&larr; Monitor</Link>
            <Link to={`/research/${ticker}`} className="text-indigo-400 hover:text-indigo-300 text-sm">Full Research &rarr;</Link>
            <span className={`text-xs px-2 py-1 rounded ${connected ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'}`}>
              {connected ? 'LIVE' : 'DISCONNECTED'}
            </span>
          </div>
          <h1 className="text-3xl font-bold text-white font-mono mt-1">{ticker}</h1>
          {info && (
            <p className="text-gray-400">{info.name} &middot; {info.exchange}</p>
          )}
        </div>
        <div className="text-right">
          {price && (
            <>
              <p className="text-3xl font-mono text-white">${price.toFixed(2)}</p>
              <p className={`text-lg font-mono ${changePct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
              </p>
            </>
          )}
        </div>
      </div>

      {/* Intraday stats */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <StatCard label="Open" value={open ? `$${open.toFixed(2)}` : '—'} />
        <StatCard label="High" value={high ? `$${high.toFixed(2)}` : '—'} color={high && price && high === price ? 'text-green-400' : 'text-white'} />
        <StatCard label="Low" value={low ? `$${low.toFixed(2)}` : '—'} color={low && price && low === price ? 'text-red-400' : 'text-white'} />
        <StatCard label="Prev Close" value={prevClose ? `$${prevClose.toFixed(2)}` : '—'} />
        <StatCard label="Volume" value={volume ? volume.toLocaleString() : '—'} />
        <StatCard label="Ticks" value={ticks.length} />
      </div>

      {/* Live tick display */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="text-white font-semibold mb-3">Live Price Feed</h3>
        <div className="max-h-64 overflow-y-auto font-mono text-xs space-y-0.5">
          {ticks.length === 0 && (
            <p className="text-gray-500 text-center py-4">Waiting for price updates...</p>
          )}
          {[...ticks].reverse().map((t, i) => (
            <div key={i} className="flex justify-between text-gray-300">
              <span className="text-gray-500">{t.time}</span>
              <span className="text-white">${t.price?.toFixed(4)}</span>
              <span className="text-gray-500">{t.volume?.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Quick actions */}
      <div className="flex gap-3">
        <Link to={`/research/${ticker}`}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg">
          Full Research
        </Link>
      </div>
    </div>
  )
}

function StatCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
      <p className="text-gray-400 text-xs uppercase">{label}</p>
      <p className={`font-mono text-lg ${color}`}>{value}</p>
    </div>
  )
}
