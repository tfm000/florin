import { useState, useEffect, useRef } from 'react'

export default function SearchBar({ onSelect, placeholder = 'Search ticker or name...' }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(-1)
  const timerRef = useRef(null)
  const wrapperRef = useRef(null)

  useEffect(() => {
    if (query.length < 1) { setResults([]); setOpen(false); return }
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await fetch(`/api/research/search?q=${encodeURIComponent(query)}`)
        if (res.ok) {
          const data = await res.json()
          setResults(data)
          setOpen(data.length > 0)
        }
      } catch { /* ignore */ }
      setLoading(false)
    }, 300)
    return () => clearTimeout(timerRef.current)
  }, [query])

  useEffect(() => {
    const handleClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleKey = (e) => {
    if (!open) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelected(s => Math.min(s + 1, results.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)) }
    if (e.key === 'Enter' && selected >= 0) {
      e.preventDefault()
      handleSelect(results[selected])
    }
    if (e.key === 'Escape') setOpen(false)
  }

  const handleSelect = (item) => {
    setQuery('')
    setOpen(false)
    setSelected(-1)
    onSelect?.(item)
  }

  return (
    <div ref={wrapperRef} className="relative w-full max-w-md">
      <input
        type="text"
        value={query}
        onChange={e => { setQuery(e.target.value); setSelected(-1) }}
        onKeyDown={handleKey}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder}
        className="w-full bg-gray-800 border border-gray-600 rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
      />
      {loading && (
        <span className="absolute right-3 top-2.5 text-gray-500 text-xs">...</span>
      )}
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-gray-800 border border-gray-600 rounded-lg shadow-xl max-h-64 overflow-y-auto">
          {results.map((r, i) => (
            <div
              key={r.ticker}
              onClick={() => handleSelect(r)}
              className={`px-4 py-2 cursor-pointer flex justify-between items-center text-sm ${
                i === selected ? 'bg-indigo-600 text-white' : 'hover:bg-gray-700 text-gray-300'
              }`}
            >
              <div>
                <span className="font-mono font-semibold text-white mr-2">{r.ticker}</span>
                <span className="text-gray-400 truncate">{r.name}</span>
              </div>
              <span className="text-xs text-gray-500">{r.exchange}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
