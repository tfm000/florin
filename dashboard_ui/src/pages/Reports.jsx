import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import ReportViewer from '../components/ReportViewer'

export default function Reports() {
  const { data: reports, loading, error } = useApi('/reports')
  const [selectedId, setSelectedId] = useState(null)
  const { data: selectedReport } = useApi(
    selectedId ? `/reports/${selectedId}` : null,
    { autoFetch: !!selectedId }
  )

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-white">Analysis Reports</h1>

      {loading && <p className="text-gray-500">Loading reports...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Report List */}
        <div className="space-y-2 max-h-[70vh] overflow-y-auto">
          {(reports || []).map(r => (
            <div
              key={r.id}
              onClick={() => setSelectedId(r.id)}
              className={`bg-gray-800 rounded-lg p-3 border cursor-pointer hover:border-indigo-500 ${
                selectedId === r.id ? 'border-indigo-500' : 'border-gray-700'
              }`}
            >
              <div className="flex justify-between items-center">
                <span className="text-white font-mono font-bold">{r.ticker}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  r.final_recommendation.includes('BUY') ? 'bg-green-900/30 text-green-400' :
                  r.final_recommendation === 'HOLD' ? 'bg-yellow-900/30 text-yellow-400' :
                  'bg-red-900/30 text-red-400'
                }`}>
                  {r.final_recommendation}
                </span>
              </div>
              <div className="flex justify-between mt-1">
                <span className="text-gray-400 text-xs">
                  {r.alert_change_pct > 0 ? '+' : ''}{r.alert_change_pct.toFixed(1)}% @ ${r.alert_price.toFixed(2)}
                </span>
                <span className="text-gray-500 text-xs">{r.generated_at}</span>
              </div>
            </div>
          ))}
          {reports && reports.length === 0 && (
            <p className="text-gray-500 text-center py-8">No reports generated yet</p>
          )}
        </div>

        {/* Selected Report */}
        <div>
          {selectedReport ? (
            <ReportViewer report={selectedReport} />
          ) : (
            <p className="text-gray-500 text-center py-8">Select a report to view details</p>
          )}
        </div>
      </div>
    </div>
  )
}
