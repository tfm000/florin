import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { HISTORICAL_PERIODS, INTRADAY_PERIODS } from '../utils/periods'

// Re-export for back-compat with current consumers that import from this file.
// Phase 3 LINT-* will redirect those consumers to '../utils/periods' directly.
export { INTRADAY_TO_HISTORY, INTRADAY_KEYS } from '../utils/periods'

// Display labels for each period token. Selector renders every canonical
// historical period (per CONTEXT D-04 / RESEARCH Open Question #3 RESOLVED:
// surface all canonical periods, no curation). 1d is intraday-only by
// convention and is filtered out of the interday preset row.
const INTRADAY_LABELS = { '1Min': '1m', '5Min': '5m', '15Min': '15m', '30Min': '30m', '1Hour': '1H' }
const INTERDAY_LABELS = {
  '5d': '1W',
  '1mo': '1M', '3mo': '3M', '6mo': '6M',
  '1y': '1Y', '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y',
  'ytd': 'YTD', 'max': 'MAX',
}

const INTRADAY_PRESETS = INTRADAY_PERIODS.map(k => ({ key: k, label: INTRADAY_LABELS[k] ?? k }))
const INTERDAY_PRESETS = [
  ...HISTORICAL_PERIODS.filter(k => k !== '1d').map(k => ({ key: k, label: INTERDAY_LABELS[k] ?? k })),
  { key: 'custom', label: 'Custom' },
]

export default function PeriodSelector({ period, onPeriodChange, startDate, endDate, onCustomRange }) {
  const [showCustom, setShowCustom] = useState(period === 'custom')
  const [localStart, setLocalStart] = useState(startDate || '')
  const [localEnd, setLocalEnd] = useState(endDate || '')

  const { data: marketData } = useApi('/market/hours', { interval: 60000 })
  const usMarket = (marketData?.markets || []).find(m => m.name.includes('NYSE'))
  const marketOpen = usMarket?.is_open ?? false

  const handlePreset = (key) => {
    if (key === 'custom') {
      setShowCustom(true)
      return
    }
    setShowCustom(false)
    onPeriodChange(key)
  }

  const handleApply = () => {
    if (localStart && localEnd && localStart < localEnd) {
      onCustomRange(localStart, localEnd)
    }
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Intraday intervals */}
      <div className="flex items-center gap-1 border-r border-gray-700 pr-2 mr-1">
        <span className="text-gray-500 text-[10px] uppercase font-semibold mr-1">Intraday</span>
        {INTRADAY_PRESETS.map(p => (
          <button
            key={p.key}
            onClick={() => handlePreset(p.key)}
            disabled={!marketOpen}
            title={!marketOpen ? 'Available when US market is open' : ''}
            className={`px-2 py-1 text-xs rounded ${
              period === p.key
                ? 'bg-indigo-600 text-white'
                : !marketOpen
                  ? 'text-gray-600 cursor-not-allowed'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Interday intervals */}
      {INTERDAY_PRESETS.map(p => (
        <button
          key={p.key}
          onClick={() => handlePreset(p.key)}
          className={`px-2 py-1 text-xs rounded ${
            (p.key === 'custom' && period === 'custom') || (p.key !== 'custom' && period === p.key)
              ? 'bg-indigo-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          {p.label}
        </button>
      ))}
      {showCustom && (
        <div className="flex items-center gap-1 ml-1">
          <input
            type="date"
            value={localStart}
            onChange={e => setLocalStart(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white"
          />
          <span className="text-gray-500 text-xs">to</span>
          <input
            type="date"
            value={localEnd}
            onChange={e => setLocalEnd(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white"
          />
          <button
            onClick={handleApply}
            disabled={!localStart || !localEnd || localStart >= localEnd}
            className="px-2 py-1 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-gray-600"
          >
            Apply
          </button>
        </div>
      )}
    </div>
  )
}
