import { useApi } from '../hooks/useApi'
import StockTable from '../components/StockTable'

export default function Universe() {
  const { data: stocks, loading, error } = useApi('/universe')

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-white">Penny Stock Universe</h1>
        {stocks && (
          <span className="text-gray-400 text-sm">{stocks.length} stocks</span>
        )}
      </div>

      {loading && <p className="text-gray-500">Loading universe...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}
      {stocks && <StockTable stocks={stocks} />}
    </div>
  )
}
