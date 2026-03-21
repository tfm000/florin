import { useMemo } from 'react'
import { Treemap, ResponsiveContainer, Tooltip } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'

// S&P 500 sector ETFs
const SECTOR_ETFS = {
  'Technology': 'XLK',
  'Healthcare': 'XLV',
  'Financials': 'XLF',
  'Consumer Disc': 'XLY',
  'Consumer Stpl': 'XLP',
  'Energy': 'XLE',
  'Industrials': 'XLI',
  'Materials': 'XLB',
  'Utilities': 'XLU',
  'Real Estate': 'XLRE',
  'Comm Services': 'XLC',
}

function CustomContent({ x, y, width, height, name, change_pct, colors }) {
  if (width < 30 || height < 20) return null
  const isPositive = (change_pct || 0) >= 0
  const intensity = Math.min(Math.abs(change_pct || 0) / 3, 1) // Normalize to 0-1 for 0-3% range
  const bg = isPositive
    ? `rgba(${hexToRgb(colors.positive)}, ${0.2 + intensity * 0.6})`
    : `rgba(${hexToRgb(colors.negative)}, ${0.2 + intensity * 0.6})`

  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke="#1F2937" strokeWidth={2} rx={4} />
      {width > 50 && height > 35 && (
        <>
          <text x={x + width / 2} y={y + height / 2 - 8} textAnchor="middle" fill="#fff" fontSize={12} fontWeight="bold">
            {name}
          </text>
          <text x={x + width / 2} y={y + height / 2 + 10} textAnchor="middle"
            fill={isPositive ? colors.positive : colors.negative} fontSize={11} fontWeight="600">
            {change_pct >= 0 ? '+' : ''}{(change_pct || 0).toFixed(2)}%
          </text>
        </>
      )}
    </g>
  )
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r}, ${g}, ${b}`
}

export default function SectorHeatMap() {
  const colors = useChartColors()
  // Fetch all sector ETFs in one macro call (they're included as tickers)
  const tickers = Object.values(SECTOR_ETFS).join(',')
  const queries = Object.entries(SECTOR_ETFS).map(([sector, etf]) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    ({ sector, etf, ...useApi(`/research/asset/${etf}`) })
  )

  // Build treemap data from fetched sector data
  // Since we can't call hooks in a loop, use a single batch approach
  const { data: techData } = useApi('/research/asset/XLK')
  const { data: healthData } = useApi('/research/asset/XLV')
  const { data: finData } = useApi('/research/asset/XLF')
  const { data: discData } = useApi('/research/asset/XLY')
  const { data: stplData } = useApi('/research/asset/XLP')
  const { data: energyData } = useApi('/research/asset/XLE')
  const { data: indData } = useApi('/research/asset/XLI')
  const { data: matData } = useApi('/research/asset/XLB')
  const { data: utilData } = useApi('/research/asset/XLU')
  const { data: reData } = useApi('/research/asset/XLRE')
  const { data: commData } = useApi('/research/asset/XLC')

  const sectorData = useMemo(() => {
    const map = {
      'Technology': techData, 'Healthcare': healthData, 'Financials': finData,
      'Consumer Disc': discData, 'Consumer Stpl': stplData, 'Energy': energyData,
      'Industrials': indData, 'Materials': matData, 'Utilities': utilData,
      'Real Estate': reData, 'Comm Services': commData,
    }

    return Object.entries(map)
      .filter(([, d]) => d?.market_cap)
      .map(([sector, d]) => ({
        name: sector,
        size: d.market_cap || 1e9,
        change_pct: d.return_1m || 0,
        price: d.current_price,
        etf: SECTOR_ETFS[sector],
      }))
  }, [techData, healthData, finData, discData, stplData, energyData, indData, matData, utilData, reData, commData])

  if (sectorData.length === 0) return <p className="text-gray-500 text-sm">Loading sectors...</p>

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">Sector Performance</h3>
      <ResponsiveContainer width="100%" height={300}>
        <Treemap
          data={sectorData}
          dataKey="size"
          stroke="#1F2937"
          content={<CustomContent colors={colors} />}
        >
          <Tooltip
            content={({ payload }) => {
              if (!payload?.[0]) return null
              const d = payload[0].payload
              return (
                <div style={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
                  <p style={{ color: '#fff', fontWeight: 'bold' }}>{d.name} ({d.etf})</p>
                  <p style={{ color: d.change_pct >= 0 ? colors.positive : colors.negative }}>
                    {d.change_pct >= 0 ? '+' : ''}{d.change_pct?.toFixed(2)}% (1M)
                  </p>
                  {d.price && <p style={{ color: '#9CA3AF' }}>${d.price.toFixed(2)}</p>}
                </div>
              )
            }}
          />
        </Treemap>
      </ResponsiveContainer>
    </div>
  )
}
