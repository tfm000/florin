import { useState } from 'react'

const PRESETS = [
  { key: '5d', label: '1W' },
  { key: '1mo', label: '1M' },
  { key: '3mo', label: '3M' },
  { key: '6mo', label: '6M' },
  { key: '1y', label: '1Y' },
  { key: '3y', label: '3Y' },
  { key: 'max', label: 'MAX' },
  { key: 'custom', label: 'Custom' },
]

export default function PeriodSelector({ period, onPeriodChange, startDate, endDate, onCustomRange }) {
  const [showCustom, setShowCustom] = useState(period === 'custom')
  const [localStart, setLocalStart] = useState(startDate || '')
  const [localEnd, setLocalEnd] = useState(endDate || '')

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
      {PRESETS.map(p => (
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
