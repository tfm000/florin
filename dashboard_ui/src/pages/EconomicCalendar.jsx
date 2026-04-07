import { useState, useMemo, useCallback } from 'react'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

const COUNTRY_PILLS = ['All', 'US', 'EU', 'GB', 'JP', 'CA', 'AU', 'NZ', 'CH', 'SE', 'NO']
const CATEGORY_PILLS = [
  'All', 'Monetary Policy', 'Inflation', 'Employment', 'Growth',
  'Housing', 'Consumer', 'Manufacturing', 'Trade', 'Government',
]

/**
 * Country flag emoji helper. Maps 2-letter country codes to flag emoji.
 * Falls back to the code itself for unrecognised or EU-style codes.
 */
function countryFlag(code) {
  if (!code) return ''
  if (code === 'EU') return '\u{1F1EA}\u{1F1FA}'
  if (code.length === 2) {
    const cp = [...code.toUpperCase()].map(c => 0x1F1E6 + c.charCodeAt(0) - 65)
    return String.fromCodePoint(...cp)
  }
  return code
}

/**
 * Formats large numbers into human-readable form (e.g. 1.2B, 340M).
 */
function formatValue(val) {
  if (val == null || val === '') return '\u2014'
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return val
  if (Math.abs(num) >= 1e12) return `${(num / 1e12).toFixed(2)}T`
  if (Math.abs(num) >= 1e9) return `${(num / 1e9).toFixed(2)}B`
  if (Math.abs(num) >= 1e6) return `${(num / 1e6).toFixed(2)}M`
  if (Math.abs(num) >= 1e3) return `${(num / 1e3).toFixed(1)}K`
  return typeof num === 'number' ? num.toLocaleString() : val
}

/**
 * Inline expandable row for an economic event.
 * When expanded, shows metadata and fetches indicator history for a sparkline chart.
 */
function EconRow({ event, isExpanded, onToggle }) {
  const today = new Date().toISOString().split('T')[0]
  const isPast = event.date < today
  const hasSurprise = event.actual && event.expected && event.actual !== event.expected

  const { data: historyData, loading: histLoading } = useApi(
    isExpanded && event.indicator_key
      ? `/calendar/indicators/${event.indicator_key}/history`
      : null
  )

  const chartData = useMemo(() => {
    if (!historyData || !Array.isArray(historyData)) return []
    return historyData.map(p => ({
      date: p.date,
      value: parseFloat(p.value),
    })).filter(p => !isNaN(p.value))
  }, [historyData])

  return (
    <div className={`bg-gray-900 rounded ${isPast ? 'opacity-80' : ''}`}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left p-3 hover:bg-gray-800/50 rounded transition-colors"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <span className="text-sm" title={event.country_name || event.country}>
              {countryFlag(event.country)}
            </span>
            <p className="text-white text-sm font-medium">{event.event}</p>
          </div>
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
      </button>

      {isExpanded && (
        <div className="px-3 pb-3 border-t border-gray-700/50 mt-1 pt-3 space-y-3">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {event.institution && (
              <>
                <span className="text-gray-500">Institution</span>
                <span className="text-gray-300">{event.institution}</span>
              </>
            )}
            {event.country_name && (
              <>
                <span className="text-gray-500">Country</span>
                <span className="text-gray-300">{event.country_name}</span>
              </>
            )}
            {event.category && (
              <>
                <span className="text-gray-500">Category</span>
                <span className="text-gray-300">{event.category}</span>
              </>
            )}
            {event.frequency && (
              <>
                <span className="text-gray-500">Frequency</span>
                <span className="text-gray-300">{event.frequency}</span>
              </>
            )}
            {event.unit && (
              <>
                <span className="text-gray-500">Unit</span>
                <span className="text-gray-300">{event.unit}</span>
              </>
            )}
          </div>
          {event.description && (
            <p className="text-xs text-gray-400 italic">{event.description}</p>
          )}

          {event.indicator_key && (
            <div className="mt-2">
              {histLoading && (
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  Loading history...
                </div>
              )}
              {!histLoading && chartData.length > 0 && (
                <div className="bg-gray-800 rounded p-2">
                  <p className="text-xs text-gray-500 mb-1">Historical trend</p>
                  <ResponsiveContainer width="100%" height={120}>
                    <LineChart data={chartData}>
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 10, fill: '#6b7280' }}
                        tickLine={false}
                        axisLine={{ stroke: '#374151' }}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: '#6b7280' }}
                        tickLine={false}
                        axisLine={false}
                        width={50}
                        domain={['auto', 'auto']}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '6px' }}
                        labelStyle={{ color: '#9ca3af', fontSize: 11 }}
                        itemStyle={{ color: '#818cf8', fontSize: 11 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="#818cf8"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              {!histLoading && chartData.length === 0 && (
                <p className="text-xs text-gray-600">No historical data available.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Expandable card for a US economic indicator (alpha_vantage source).
 * Shows key values and expands with a historical chart on click.
 */
function IndicatorCard({ event, isExpanded, onToggle }) {
  const { data: historyData, loading: histLoading } = useApi(
    isExpanded && event.indicator_key
      ? `/calendar/indicators/${event.indicator_key}/history`
      : null
  )

  const chartData = useMemo(() => {
    if (!historyData || !Array.isArray(historyData)) return []
    return historyData.map(p => ({
      date: p.date,
      value: parseFloat(p.value),
    })).filter(p => !isNaN(p.value))
  }, [historyData])

  return (
    <div className="bg-gray-900 rounded border border-gray-700/50">
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left p-4 hover:bg-gray-800/50 rounded transition-colors"
      >
        <p className="text-white text-sm font-medium mb-2">{event.event}</p>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div>
            <span className="text-gray-500 block">Actual</span>
            <span className="text-white font-mono">
              {event.actual ? formatValue(event.actual) : '\u2014'}
            </span>
          </div>
          <div>
            <span className="text-gray-500 block">Previous</span>
            <span className="text-gray-400 font-mono">
              {event.previous ? formatValue(event.previous) : '\u2014'}
            </span>
          </div>
          <div>
            <span className="text-gray-500 block">Period</span>
            <span className="text-gray-400">{event.date || '\u2014'}</span>
          </div>
        </div>
        {event.unit && (
          <p className="text-xs text-gray-600 mt-1">Unit: {event.unit}</p>
        )}
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 border-t border-gray-700/50 pt-3">
          {event.description && (
            <p className="text-xs text-gray-400 italic mb-2">{event.description}</p>
          )}
          {histLoading && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              Loading history...
            </div>
          )}
          {!histLoading && chartData.length > 0 && (
            <div className="bg-gray-800 rounded p-2">
              <ResponsiveContainer width="100%" height={140}>
                <LineChart data={chartData}>
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: '#6b7280' }}
                    tickLine={false}
                    axisLine={{ stroke: '#374151' }}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#6b7280' }}
                    tickLine={false}
                    axisLine={false}
                    width={55}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '6px' }}
                    labelStyle={{ color: '#9ca3af', fontSize: 11 }}
                    itemStyle={{ color: '#818cf8', fontSize: 11 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#818cf8"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          {!histLoading && chartData.length === 0 && (
            <p className="text-xs text-gray-600">No historical data available.</p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Economic Calendar page. Displays two sections:
 *
 * Section A: Central Bank Meetings & global economic events,
 *   filterable by country and category, with expandable detail rows and sparklines.
 *
 * Section B: US Economic Indicators (source=alpha_vantage),
 *   displayed as a card grid with expandable historical charts.
 */
export default function EconomicCalendar() {
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [showPast, setShowPast] = useState(false)
  const [countryFilter, setCountryFilter] = useState('All')
  const [categoryFilter, setCategoryFilter] = useState('All')
  const [expandedKey, setExpandedKey] = useState(null)
  const [expandedIndicator, setExpandedIndicator] = useState(null)

  const dateParams = [
    startDate && `start_date=${startDate}`,
    endDate && `end_date=${endDate}`,
  ].filter(Boolean).join('&')

  const { data, loading } = useApi(`/calendar${dateParams ? `?${dateParams}` : ''}`)

  const economic = data?.economic || []
  const today = new Date().toISOString().split('T')[0]

  /** Central bank / global events (exclude alpha_vantage source). */
  const cbEvents = useMemo(() => {
    return economic.filter(e => e.source !== 'alpha_vantage')
  }, [economic])

  /** US economic indicators from alpha_vantage. */
  const usIndicators = useMemo(() => {
    return economic.filter(e => e.source === 'alpha_vantage')
  }, [economic])

  /** Filtered CB events based on country, category, and past toggle. */
  const filteredCB = useMemo(() => {
    let items = cbEvents
    if (countryFilter !== 'All') {
      items = items.filter(e => e.country === countryFilter)
    }
    if (categoryFilter !== 'All') {
      items = items.filter(e => e.category === categoryFilter)
    }
    const upcoming = items.filter(e => e.date >= today)
    const past = items.filter(e => e.date < today)
    return { upcoming, past }
  }, [cbEvents, countryFilter, categoryFilter, today])

  /** Build a unique key for toggling expansion on CB event rows. */
  const eventKey = useCallback((e, i) => `${e.date}-${e.event}-${i}`, [])

  /** Unique categories present in the data, for dynamic category pills. */
  const availableCategories = useMemo(() => {
    const cats = new Set(cbEvents.map(e => e.category).filter(Boolean))
    return ['All', ...CATEGORY_PILLS.slice(1).filter(c => cats.has(c)),
      ...[...cats].filter(c => !CATEGORY_PILLS.includes(c)).sort()]
  }, [cbEvents])

  return (
    <div className="space-y-8">
      {/* Section A: Central Bank Meetings & Events */}
      <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Central Bank Meetings & Events</h2>
          {cbEvents.length > 0 && (
            <ExportButton data={cbEvents} filename="economic_events" />
          )}
        </div>

        {/* Filters */}
        <div className="space-y-3 mb-4">
          {/* Country pills */}
          <div className="flex flex-wrap gap-1">
            {COUNTRY_PILLS.map(code => (
              <button
                key={code}
                onClick={() => setCountryFilter(code)}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  countryFilter === code
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-300'
                }`}
              >
                {code === 'All' ? 'All Countries' : `${countryFlag(code)} ${code}`}
              </button>
            ))}
          </div>

          {/* Category pills */}
          <div className="flex flex-wrap gap-1">
            {availableCategories.map(cat => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(cat)}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  categoryFilter === cat
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-300'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>

          {/* Date range + show past */}
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
            <button
              onClick={() => setShowPast(!showPast)}
              className={`px-3 py-1 text-xs rounded transition-colors ${
                showPast ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              {showPast ? 'Showing Past' : 'Show Past'}
            </button>
          </div>
        </div>

        {loading && <p className="text-gray-500 text-sm">Loading economic events...</p>}

        {/* Upcoming events */}
        {!loading && (
          <>
            <p className="text-xs text-gray-500 mb-2 uppercase tracking-wide">Upcoming</p>
            <div className="space-y-2 max-h-[32rem] overflow-y-auto mb-4">
              {filteredCB.upcoming.length === 0 && (
                <p className="text-gray-600 text-sm">No upcoming events match your filters.</p>
              )}
              {filteredCB.upcoming.map((e, i) => {
                const key = eventKey(e, i)
                return (
                  <EconRow
                    key={key}
                    event={e}
                    isExpanded={expandedKey === key}
                    onToggle={() => setExpandedKey(expandedKey === key ? null : key)}
                  />
                )
              })}
            </div>

            {/* Past events */}
            {showPast && filteredCB.past.length > 0 && (
              <>
                <p className="text-xs text-gray-500 mb-2 uppercase tracking-wide">Past</p>
                <div className="space-y-2 max-h-[32rem] overflow-y-auto">
                  {filteredCB.past.map((e, i) => {
                    const key = `past-${eventKey(e, i)}`
                    return (
                      <EconRow
                        key={key}
                        event={e}
                        isExpanded={expandedKey === key}
                        onToggle={() => setExpandedKey(expandedKey === key ? null : key)}
                      />
                    )
                  })}
                </div>
              </>
            )}
          </>
        )}
      </div>

      {/* Section B: US Economic Indicators */}
      <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">US Economic Indicators</h2>
          {usIndicators.length > 0 && (
            <ExportButton data={usIndicators} filename="us_economic_indicators" />
          )}
        </div>

        {loading && <p className="text-gray-500 text-sm">Loading indicators...</p>}

        {!loading && usIndicators.length === 0 && (
          <p className="text-gray-600 text-sm">No US economic indicator data available.</p>
        )}

        {!loading && usIndicators.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {usIndicators.map((e, i) => {
              const key = `ind-${e.indicator_key || i}`
              return (
                <IndicatorCard
                  key={key}
                  event={e}
                  isExpanded={expandedIndicator === key}
                  onToggle={() => setExpandedIndicator(expandedIndicator === key ? null : key)}
                />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
