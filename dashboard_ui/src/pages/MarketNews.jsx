import { useState } from 'react'
import { useApi } from '../hooks/useApi'

export default function MarketNews() {
  const { data: articles, loading, refetch } = useApi('/news/feed')
  const [filter, setFilter] = useState('')

  const filtered = (articles || []).filter(a =>
    !filter || a.headline.toLowerCase().includes(filter.toLowerCase()) ||
    a.source.toLowerCase().includes(filter.toLowerCase())
  )

  // Group by source
  const sources = [...new Set((articles || []).map(a => a.source))].filter(Boolean)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Market News</h1>
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter headlines..."
            className="bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 w-64"
          />
          <button onClick={refetch}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded">
            Refresh
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-500">Fetching news from RSS feeds...</p>}

      {/* Source filter buttons */}
      {sources.length > 0 && (
        <div className="flex flex-wrap gap-1">
          <button
            onClick={() => setFilter('')}
            className={`px-2 py-0.5 text-xs rounded ${!filter ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}
          >
            All
          </button>
          {sources.map(s => (
            <button key={s} onClick={() => setFilter(s)}
              className={`px-2 py-0.5 text-xs rounded ${filter === s ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Articles */}
      <div className="space-y-3">
        {filtered.map((a, i) => (
          <a key={i} href={a.url || '#'} target="_blank" rel="noopener noreferrer"
            className="block bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-gray-500 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <p className="text-white font-medium leading-snug">{a.headline}</p>
                {a.excerpt && (
                  <p className="text-gray-400 text-sm mt-1 line-clamp-2">{a.excerpt}</p>
                )}
              </div>
              <div className="text-right shrink-0">
                <p className="text-xs text-indigo-400">{a.source}</p>
                {a.pub_date && (
                  <p className="text-xs text-gray-500 mt-1">
                    {new Date(a.pub_date).toLocaleDateString()}
                  </p>
                )}
              </div>
            </div>
          </a>
        ))}
      </div>

      {!loading && filtered.length === 0 && (
        <p className="text-gray-500 text-center py-8">No news articles found</p>
      )}
    </div>
  )
}
