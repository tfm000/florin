import { useState } from 'react'
import { useApi } from '../hooks/useApi'

const fmtShares = (n) => {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toLocaleString()
}

const fmtValue = (n) => {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  return `$${n.toLocaleString()}`
}

export default function TopHolders({ ticker }) {
  const { data, loading } = useApi(`/research/holders/${ticker}`)
  const [tab, setTab] = useState('institutional')

  if (loading) return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-2">Top Holders</h3>
      <p className="text-gray-500 text-sm">Loading holder data...</p>
    </div>
  )

  if (!data || (!data.institutional?.length && !data.mutual_fund?.length)) return null

  const major = data.major
  const holders = tab === 'institutional' ? data.institutional : data.mutual_fund

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
      <h3 className="text-white font-semibold">Top Holders</h3>

      {/* Major holders breakdown */}
      {major && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-gray-900/50 rounded-lg p-2.5">
            <p className="text-gray-500 text-xs uppercase">Insiders</p>
            <p className="text-white font-mono text-sm">{major.insiders_pct.toFixed(2)}%</p>
          </div>
          <div className="bg-gray-900/50 rounded-lg p-2.5">
            <p className="text-gray-500 text-xs uppercase">Institutions</p>
            <p className="text-white font-mono text-sm">{major.institutions_pct.toFixed(2)}%</p>
          </div>
          <div className="bg-gray-900/50 rounded-lg p-2.5">
            <p className="text-gray-500 text-xs uppercase">Inst. Float</p>
            <p className="text-white font-mono text-sm">{major.institutions_float_pct.toFixed(2)}%</p>
          </div>
          <div className="bg-gray-900/50 rounded-lg p-2.5">
            <p className="text-gray-500 text-xs uppercase">Inst. Count</p>
            <p className="text-white font-mono text-sm">{major.institutions_count.toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* Tab switcher */}
      <div className="flex gap-1 bg-gray-900/50 rounded-lg p-0.5 w-fit">
        <button
          onClick={() => setTab('institutional')}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            tab === 'institutional'
              ? 'bg-gray-700 text-white'
              : 'text-gray-400 hover:text-gray-300'
          }`}
        >
          Institutional ({data.institutional?.length || 0})
        </button>
        <button
          onClick={() => setTab('mutual_fund')}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            tab === 'mutual_fund'
              ? 'bg-gray-700 text-white'
              : 'text-gray-400 hover:text-gray-300'
          }`}
        >
          Mutual Funds ({data.mutual_fund?.length || 0})
        </button>
      </div>

      {/* Holders table */}
      {holders && holders.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-900/50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Holder</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Shares</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Value</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">% Held</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">% Change</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Reported</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {holders.map((h, i) => (
                <tr key={i} className="hover:bg-gray-700/30">
                  <td className="px-3 py-2 text-white text-xs max-w-[250px] truncate" title={h.holder}>
                    {h.holder}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-300 text-xs">
                    {fmtShares(h.shares)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-300 text-xs">
                    {fmtValue(h.value)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-300 text-xs">
                    {h.pct_held.toFixed(2)}%
                  </td>
                  <td className={`px-3 py-2 text-right font-mono text-xs ${
                    h.pct_change > 0 ? 'text-green-400' : h.pct_change < 0 ? 'text-red-400' : 'text-gray-400'
                  }`}>
                    {h.pct_change > 0 ? '+' : ''}{h.pct_change.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500 text-xs">
                    {h.date_reported}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
