import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, apiPost, apiPut, apiDelete } from '../hooks/useApi'
import SearchBar from '../components/SearchBar'
import ExportButton from '../components/ExportButton'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'

const PIE_COLORS = ['#6366F1', '#22C55E', '#F59E0B', '#EF4444', '#EC4899', '#14B8A6', '#8B5CF6', '#F97316']

export default function Portfolio() {
  const navigate = useNavigate()
  const { data: portfolios, refetch } = useApi('/portfolios')
  const [selectedId, setSelectedId] = useState('')
  const [newName, setNewName] = useState('')
  const [editHoldings, setEditHoldings] = useState(null) // [{ticker, weight}]

  const selected = (portfolios || []).find(p => p.id === selectedId)
  const { data: analytics } = useApi(
    selectedId ? `/portfolios/${selectedId}/analytics?period=1y` : null,
    { autoFetch: !!selectedId }
  )

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      const p = await apiPost('/portfolios', { name: newName.trim() })
      setNewName('')
      refetch()
      setSelectedId(p.id)
    } catch { /* ignore */ }
  }

  const handleDelete = async () => {
    if (!selectedId || !confirm('Delete this portfolio?')) return
    await apiDelete(`/portfolios/${selectedId}`)
    setSelectedId('')
    refetch()
  }

  const startEdit = () => {
    setEditHoldings(selected?.holdings?.map(h => ({ ...h })) || [])
  }

  const addHolding = (item) => {
    const sym = item.ticker.toUpperCase()
    if (!editHoldings.find(h => h.ticker === sym)) {
      setEditHoldings(prev => [...prev, { ticker: sym, weight: 0 }])
    }
  }

  const updateWeight = (ticker, weight) => {
    setEditHoldings(prev => prev.map(h => h.ticker === ticker ? { ...h, weight: Number(weight) } : h))
  }

  const removeHolding = (ticker) => {
    setEditHoldings(prev => prev.filter(h => h.ticker !== ticker))
  }

  const saveHoldings = async () => {
    if (!selectedId) return
    await apiPut(`/portfolios/${selectedId}/holdings`, editHoldings)
    setEditHoldings(null)
    refetch()
  }

  const totalWeight = editHoldings?.reduce((s, h) => s + h.weight, 0) || 0
  const holdings = editHoldings || selected?.holdings || []

  // Pie chart data
  const pieData = holdings.filter(h => h.weight > 0).map(h => ({ name: h.ticker, value: h.weight }))

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Portfolios</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Portfolio list */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">Model Portfolios</h2>
          <div className="flex gap-2 mb-3">
            <input type="text" value={newName} onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder="New portfolio name..."
              className="flex-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white" />
            <button onClick={handleCreate} className="px-3 py-1 bg-indigo-600 text-white text-sm rounded">Create</button>
          </div>
          <div className="space-y-2">
            {/* Ungrouped portfolios first */}
            {(portfolios || []).filter(p => !p.group).map(p => (
              <div key={p.id} onClick={() => navigate(`/portfolio/${p.id}`)}
                className={`p-2 rounded cursor-pointer text-sm ${
                  selectedId === p.id ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-300 hover:bg-gray-700'
                }`}>
                <p className="font-medium">{p.name}</p>
                <p className="text-xs opacity-70">{p.holdings?.length || 0} holdings</p>
              </div>
            ))}
            {/* Grouped portfolios */}
            {[...new Set((portfolios || []).filter(p => p.group).map(p => p.group))].map(group => (
              <div key={group}>
                <p className="text-xs text-gray-500 uppercase font-semibold mt-3 mb-1">{group}</p>
                {(portfolios || []).filter(p => p.group === group).map(p => (
                  <div key={p.id} onClick={() => navigate(`/portfolio/${p.id}`)}
                    className={`p-2 rounded cursor-pointer text-sm ${
                      selectedId === p.id ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-300 hover:bg-gray-700'
                    }`}>
                    <p className="font-medium">{p.name}</p>
                    <p className="text-xs opacity-70">{p.holdings?.length || 0} holdings</p>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* Holdings editor */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold">{selected ? selected.name : 'Select a portfolio'}</h2>
            {selected && !editHoldings && (
              <div className="flex gap-2">
                <button onClick={startEdit} className="px-2 py-1 text-xs bg-gray-700 text-white rounded">Edit</button>
                <button onClick={handleDelete} className="px-2 py-1 text-xs bg-red-700 text-white rounded">Delete</button>
              </div>
            )}
          </div>

          {editHoldings && (
            <>
              <SearchBar onSelect={addHolding} placeholder="Add ticker..." />
              <div className="mt-3 space-y-2 max-h-64 overflow-y-auto">
                {editHoldings.map(h => (
                  <div key={h.ticker} className="flex items-center gap-2">
                    <span className="text-white font-mono text-sm w-16">{h.ticker}</span>
                    <input type="number" value={h.weight} onChange={e => updateWeight(h.ticker, e.target.value)}
                      min={0} max={100} step={0.5}
                      className="w-20 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white" />
                    <span className="text-gray-500 text-xs">%</span>
                    <button onClick={() => removeHolding(h.ticker)} className="text-red-500 text-xs">&times;</button>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between mt-3">
                <span className={`text-xs ${Math.abs(totalWeight - 100) < 0.01 ? 'text-green-400' : 'text-yellow-400'}`}>
                  Total: {totalWeight.toFixed(1)}%
                </span>
                <div className="flex gap-2">
                  <button onClick={() => setEditHoldings(null)} className="px-2 py-1 text-xs bg-gray-700 text-white rounded">Cancel</button>
                  <button onClick={saveHoldings} className="px-2 py-1 text-xs bg-indigo-600 text-white rounded">Save</button>
                </div>
              </div>
            </>
          )}

          {!editHoldings && selected && (
            <div className="space-y-1">
              {holdings.map(h => (
                <div key={h.ticker} className="flex justify-between text-sm">
                  <span className="text-white font-mono">{h.ticker}</span>
                  <span className="text-gray-400">{h.weight.toFixed(1)}%</span>
                </div>
              ))}
              {holdings.length > 0 && <ExportButton data={holdings} filename={`portfolio_${selected.name}`} />}
            </div>
          )}
        </div>

        {/* Allocation pie + analytics */}
        <div className="space-y-4">
          {pieData.length > 0 && (
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-white font-semibold mb-2">Allocation</h3>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                    innerRadius={40} outerRadius={80}
                    label={({ name, value }) => `${name} ${value}%`} labelLine={false}>
                    {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={v => `${v}%`} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          {analytics && analytics.total_return !== 0 && (
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-white font-semibold mb-2">Analytics (1Y)</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <Stat label="Return" value={`${analytics.total_return}%`} color={analytics.total_return >= 0 ? 'text-green-400' : 'text-red-400'} />
                <Stat label="Vol" value={`${analytics.annualized_vol}%`} />
                <Stat label="Sharpe" value={analytics.sharpe.toFixed(2)} color={analytics.sharpe >= 0 ? 'text-green-400' : 'text-red-400'} />
                <Stat label="Sortino" value={analytics.sortino.toFixed(2)} />
                <Stat label="Max DD" value={`${analytics.max_drawdown}%`} color="text-red-400" />
                <Stat label="VaR(95%)" value={`${analytics.var_95}%`} color="text-red-400" />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, color = 'text-white' }) {
  return (
    <div>
      <p className="text-gray-500">{label}</p>
      <p className={`font-mono ${color}`}>{value}</p>
    </div>
  )
}
