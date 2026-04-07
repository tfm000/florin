import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

/**
 * Formats a number as a compact dollar string (e.g. $21.97B, $1.94).
 */
function formatDollar(val) {
  if (val == null) return '\u2014'
  if (Math.abs(val) >= 1e12) return `$${(val / 1e12).toFixed(2)}T`
  if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(2)}B`
  if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toFixed(2)}`
}

/**
 * Returns a default date range: today to 4 weeks from now, as ISO date strings.
 */
function defaultDateRange() {
  const now = new Date()
  const start = now.toISOString().split('T')[0]
  const end = new Date(now.getTime() + 28 * 86400000).toISOString().split('T')[0]
  return { start, end }
}

/**
 * Badge component for reporting hour (Before Market Open / After Market Close).
 */
function HourBadge({ hour }) {
  if (!hour || (hour !== 'bmo' && hour !== 'amc')) return null
  const isBMO = hour === 'bmo'
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
      isBMO ? 'bg-green-900 text-green-300' : 'bg-blue-900 text-blue-300'
    }`}>
      {isBMO ? 'BMO' : 'AMC'}
    </span>
  )
}

/**
 * Card for an upcoming earnings event.
 * Watchlist tickers are highlighted with an indigo left border.
 */
function UpcomingEarningsCard({ event, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left bg-gray-900 rounded p-4 hover:bg-gray-800 transition-colors cursor-pointer ${
        event.in_watchlist ? 'border-l-4 border-indigo-500' : ''
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <p className="text-white font-mono font-bold text-sm">{event.ticker}</p>
          {event.in_watchlist && (
            <span className="text-xs bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">
              Watchlist
            </span>
          )}
          <HourBadge hour={event.hour} />
        </div>
        <span className="text-gray-400 text-xs">{event.date}</span>
      </div>
      {event.name && (
        <p className="text-gray-500 text-xs mb-2 truncate">{event.name}</p>
      )}
      <div className="flex gap-4 text-xs">
        {event.eps_estimate != null && (
          <div>
            <span className="text-gray-500">EPS Est: </span>
            <span className="text-gray-300 font-mono">${event.eps_estimate.toFixed(2)}</span>
          </div>
        )}
        {event.revenue_estimate != null && (
          <div>
            <span className="text-gray-500">Rev Est: </span>
            <span className="text-gray-300 font-mono">{formatDollar(event.revenue_estimate)}</span>
          </div>
        )}
      </div>
    </button>
  )
}

/**
 * Earnings Calendar page.
 *
 * Fetches earnings data from /api/calendar for watchlist tickers and displays:
 * - Upcoming earnings as interactive cards
 * - Past earnings as a sortable table with surprise highlighting
 *
 * Both sections support date range filtering, ticker search, and a past toggle.
 */
export default function EarningsCalendar() {
  const defaults = defaultDateRange()
  const navigate = useNavigate()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [showPast, setShowPast] = useState(false)
  const [tickerSearch, setTickerSearch] = useState('')

  const { data: watchlist } = useApi('/watchlist?limit=100')
  const watchlistTickers = (watchlist?.items || []).map(i => i.ticker).join(',')

  const dateParams = [
    startDate && `start_date=${startDate}`,
    endDate && `end_date=${endDate}`,
    watchlistTickers && `tickers=${watchlistTickers}`,
  ].filter(Boolean).join('&')

  const { data, loading } = useApi(
    watchlistTickers ? `/calendar?${dateParams}` : null
  )

  const earnings = data?.earnings || []

  /** Apply ticker search filter across all earnings. */
  const filtered = useMemo(() => {
    if (!tickerSearch.trim()) return earnings
    const q = tickerSearch.trim().toUpperCase()
    return earnings.filter(e => e.ticker.includes(q))
  }, [earnings, tickerSearch])

  const upcoming = useMemo(() => filtered.filter(e => e.is_future), [filtered])
  const past = useMemo(() => filtered.filter(e => !e.is_future), [filtered])

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-xs text-gray-400">
          From:
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs"
          />
        </label>
        <label className="text-xs text-gray-400">
          To:
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            className="ml-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs"
          />
        </label>
        <input
          type="text"
          value={tickerSearch}
          onChange={e => setTickerSearch(e.target.value)}
          placeholder="Filter by ticker..."
          className="bg-gray-700 border border-gray-600 rounded px-3 py-1 text-white text-xs placeholder-gray-500 w-40"
        />
        <button
          onClick={() => setShowPast(!showPast)}
          className={`px-3 py-1 text-xs rounded transition-colors ${
            showPast ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
          }`}
        >
          {showPast ? 'Showing Past' : 'Show Past'}
        </button>
        {earnings.length > 0 && (
          <ExportButton data={earnings} filename="earnings_calendar" />
        )}
      </div>

      {!watchlistTickers && !loading && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 text-center">
          <p className="text-gray-400 text-sm">
            Add stocks to your watchlist to see their earnings dates.
          </p>
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">Loading earnings...</p>}

      {/* Upcoming Earnings */}
      {!loading && upcoming.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">
            Upcoming Earnings
            <span className="text-gray-500 text-sm font-normal ml-2">({upcoming.length})</span>
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {upcoming.map((e, i) => (
              <UpcomingEarningsCard
                key={`${e.ticker}-${e.date}-${i}`}
                event={e}
                onClick={() => navigate(`/research/${e.ticker}`)}
              />
            ))}
          </div>
        </div>
      )}

      {!loading && !upcoming.length && watchlistTickers && (
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <p className="text-gray-500 text-sm">No upcoming earnings in the selected date range.</p>
        </div>
      )}

      {/* Past Earnings */}
      {showPast && !loading && past.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">
            Past Earnings
            <span className="text-gray-500 text-sm font-normal ml-2">({past.length})</span>
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-gray-800">
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left px-3 py-2">Date</th>
                  <th className="text-left px-3 py-2">Ticker</th>
                  <th className="text-right px-3 py-2">EPS Est</th>
                  <th className="text-right px-3 py-2">Actual EPS</th>
                  <th className="text-right px-3 py-2">Surprise %</th>
                  <th className="text-right px-3 py-2">Rev Est</th>
                  <th className="text-right px-3 py-2">Rev Actual</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {past.map((e, i) => (
                  <tr
                    key={`${e.ticker}-${e.date}-${i}`}
                    onClick={() => navigate(`/research/${e.ticker}`)}
                    className="hover:bg-gray-700/30 cursor-pointer transition-colors"
                  >
                    <td className="px-3 py-2 text-gray-400">{e.date}</td>
                    <td className="px-3 py-2">
                      <span className="text-white font-mono font-semibold">{e.ticker}</span>
                      {e.in_watchlist && (
                        <span className="ml-1.5 text-indigo-400 text-[10px]">WL</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-400 font-mono">
                      {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : '\u2014'}
                    </td>
                    <td className="px-3 py-2 text-right text-white font-mono">
                      {e.reported_eps != null ? `$${e.reported_eps.toFixed(2)}` : '\u2014'}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${
                      e.surprise_pct != null && e.surprise_pct > 0 ? 'text-green-400' :
                      e.surprise_pct != null && e.surprise_pct < 0 ? 'text-red-400' :
                      'text-gray-400'
                    }`}>
                      {e.surprise_pct != null
                        ? `${e.surprise_pct > 0 ? '+' : ''}${e.surprise_pct.toFixed(1)}%`
                        : '\u2014'}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-400 font-mono">
                      {e.revenue_estimate != null ? formatDollar(e.revenue_estimate) : '\u2014'}
                    </td>
                    <td className="px-3 py-2 text-right text-white font-mono">
                      {e.revenue_actual != null ? formatDollar(e.revenue_actual) : '\u2014'}
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
