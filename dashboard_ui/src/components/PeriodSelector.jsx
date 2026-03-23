import { useState } from 'react'
import { useApi } from '../hooks/useApi'

const INTRADAY_PRESETS = [
  { key: '1Min', label: '1m' },
  { key: '5Min', label: '5m' },
  { key: '15Min', label: '15m' },
  { key: '30Min', label: '30m' },
  { key: '1Hour', label: '1H' },
]

const INTERDAY_PRESETS = [
  { key: '5d', label: '1W' },
  { key: '1mo', label: '1M' },
  { key: '3mo', label: '3M' },
  { key: '6mo', label: '6M' },
  { key: '1y', label: '1Y' },
  { key: '3y', label: '3Y' },
  { key: 'max', label: 'MAX' },
  { key: 'custom', label: 'Custom' },
]

export const INTRADAY_KEYS = new Set(INTRADAY_PRESETS.map(p => p.key))

export default function PeriodSelector({ period, onPeriodChange, startDate, endDate, onCustomRange }) {
  const [showCustom, setShowCustom] = useState(period === 'custom')
  const [localStart, setLocalStart] = useState(startDate || '')
  const [localEnd, setLocalEnd] = useState(endDate || '')

  const { data: marketData } = useApi('/market/hours', { interval: 60000 })
  const usMarket = (marketData?.markets || []).find(m => m.name === 'US (NYSE/NASDAQ)')
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
