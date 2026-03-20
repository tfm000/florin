function formatValue(value, format) {
  if (value == null) return '—'
  if (format === 'pct') return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  if (format === 'dollar') return `$${Number(value).toLocaleString()}`
  if (format === 'mcap') {
    if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
    if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
    if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
    return `$${Number(value).toLocaleString()}`
  }
  if (format === 'number') return Number(value).toFixed(2)
  return String(value)
}

export default function MetricsGrid({ metrics }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      {metrics.map(m => (
        <div key={m.label} className="bg-gray-800 rounded-lg p-3 border border-gray-700">
          <p className="text-gray-400 text-xs uppercase">{m.label}</p>
          <p className={`font-mono text-lg ${m.color || 'text-white'}`}>
            {formatValue(m.value, m.format)}
          </p>
        </div>
      ))}
    </div>
  )
}
