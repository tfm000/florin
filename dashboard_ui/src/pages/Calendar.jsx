import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

export default function Calendar() {
  const navigate = useNavigate()
  const { data: watchlist } = useApi('/watchlist?limit=100')
  const watchlistTickers = (watchlist?.items || []).map(i => i.ticker).join(',')

  // Date range for economic events
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [showPast, setShowPast] = useState(false)

  const dateParams = [
    startDate && `start_date=${startDate}`,
    endDate && `end_date=${endDate}`,
    watchlistTickers && `tickers=${watchlistTickers}`,
  ].filter(Boolean).join('&')

  const { data, loading } = useApi(`/calendar?${dateParams}`)

  const earnings = data?.earnings || []
  const economic = data?.economic || []
  const today = new Date().toISOString().split('T')[0]

  const futureEarnings = earnings.filter(e => e.is_future)
  const pastEarnings = earnings.filter(e => !e.is_future)
  const futureEcon = economic.filter(e => e.date >= today)
  const pastEcon = economic.filter(e => e.date < today)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Calendar</h1>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400">
            From:
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
              className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs" />
          </label>
          <label className="text-xs text-gray-400">
            To:
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
              className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs" />
          </label>
          <button
            onClick={() => setShowPast(!showPast)}
            className={`px-2 py-1 text-xs rounded ${showPast ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}
          >
            {showPast ? 'Showing Past' : 'Show Past'}
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading calendar...</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Economic Events */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold">Economic Events</h2>
            {economic.length > 0 && <ExportButton data={economic} filename="economic_calendar" />}
          </div>

          {/* Upcoming */}
          <p className="text-xs text-gray-500 mb-2 uppercase">Upcoming</p>
          <div className="space-y-2 max-h-64 overflow-y-auto mb-4">
            {futureEcon.length === 0 && <p className="text-gray-500 text-sm">No upcoming events in range</p>}
            {futureEcon.map((e, i) => (
              <EconRow key={`f-${i}`} event={e} />
            ))}
          </div>

          {/* Past events */}
          {showPast && pastEcon.length > 0 && (
            <>
              <p className="text-xs text-gray-500 mb-2 uppercase">Past</p>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {pastEcon.map((e, i) => (
                  <EconRow key={`p-${i}`} event={e} />
                ))}
              </div>
            </>
          )}
        </div>

        {/* Earnings */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold">Earnings</h2>
            {earnings.length > 0 && <ExportButton data={earnings} filename="earnings_calendar" />}
          </div>

          {!watchlistTickers && (
            <p className="text-gray-500 text-sm mb-3">Add stocks to your watchlist to see earnings</p>
          )}

          {/* Upcoming earnings */}
          {futureEarnings.length > 0 && (
            <>
              <p className="text-xs text-gray-500 mb-2 uppercase">Upcoming</p>
              <div className="space-y-2 max-h-48 overflow-y-auto mb-4">
                {futureEarnings.map((e, i) => (
                  <EarningsRow key={`f-${i}`} event={e} onClick={() => navigate(`/research/${e.ticker}`)} />
                ))}
              </div>
            </>
          )}

          {/* Past earnings with results */}
          {showPast && pastEarnings.length > 0 && (
            <>
              <p className="text-xs text-gray-500 mb-2 uppercase">Past (with results)</p>
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-800">
                    <tr className="text-gray-500">
                      <th className="text-left px-2 py-1">Date</th>
                      <th className="text-left px-2 py-1">Ticker</th>
                      <th className="text-right px-2 py-1">EPS Est</th>
                      <th className="text-right px-2 py-1">Actual</th>
                      <th className="text-right px-2 py-1">Surprise</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {pastEarnings.map((e, i) => (
                      <tr key={i} onClick={() => navigate(`/research/${e.ticker}`)}
                        className="hover:bg-gray-700/30 cursor-pointer">
                        <td className="px-2 py-1 text-gray-400">{e.date}</td>
                        <td className="px-2 py-1 text-white font-mono font-semibold">{e.ticker}</td>
                        <td className="px-2 py-1 text-right text-gray-400 font-mono">
                          {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : '—'}
                        </td>
                        <td className="px-2 py-1 text-right text-white font-mono">
                          {e.reported_eps != null ? `$${e.reported_eps.toFixed(2)}` : '—'}
                        </td>
                        <td className={`px-2 py-1 text-right font-mono ${
                          e.surprise_pct > 0 ? 'text-green-400' : e.surprise_pct < 0 ? 'text-red-400' : 'text-gray-400'
                        }`}>
                          {e.surprise_pct != null ? `${e.surprise_pct > 0 ? '+' : ''}${e.surprise_pct.toFixed(1)}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function EconRow({ event }) {
  const today = new Date().toISOString().split('T')[0]
  const isPast = event.date < today
  const hasSurprise = event.actual && event.expected && event.actual !== event.expected

  return (
    <div className={`bg-gray-900 rounded p-3 ${isPast ? 'opacity-80' : ''}`}>
      <div className="flex items-center justify-between mb-1">
        <p className="text-white text-sm font-medium">{event.event}</p>
        <span className={`text-xs px-2 py-0.5 rounded ${
          event.importance === 'high' ? 'bg-red-900 text-red-300' :
          event.importance === 'medium' ? 'bg-yellow-900 text-yellow-300' :
          'bg-gray-700 text-gray-400'
        }`}>
          {event.importance}
        </span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">{event.date}</span>
        <div className="flex gap-3">
          {event.expected && <span className="text-gray-400">Exp: {event.expected}</span>}
          {event.actual && (
            <span className={hasSurprise ? 'text-yellow-400 font-semibold' : 'text-gray-300'}>
              Act: {event.actual}
            </span>
          )}
          {event.previous && <span className="text-gray-500">Prev: {event.previous}</span>}
        </div>
      </div>
    </div>
  )
}

function EarningsRow({ event, onClick }) {
  return (
    <div onClick={onClick}
      className="flex items-center justify-between bg-gray-900 rounded p-3 cursor-pointer hover:bg-gray-800">
      <div>
        <p className="text-white text-sm font-mono font-semibold">{event.ticker}</p>
        <p className="text-gray-400 text-xs">{event.name}</p>
      </div>
      <div className="text-right">
        <p className="text-gray-300 text-sm">{event.date}</p>
        {event.eps_estimate != null && (
          <p className="text-gray-500 text-xs">EPS est: ${event.eps_estimate.toFixed(2)}</p>
        )}
      </div>
    </div>
  )
}
