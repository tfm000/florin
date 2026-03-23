import { useChartColors } from '../hooks/useChartColors'

export default function PositionCard({ position, onSell }) {
  const colors = useChartColors()
  const pnlColor = position.unrealised_pnl >= 0 ? colors.positive : colors.negative
  const pnlSign = position.unrealised_pnl >= 0 ? '+' : ''

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="text-white font-bold text-lg">{position.ticker}</h3>
          <p className="text-gray-400 text-sm">{position.quantity} shares @ ${position.avg_price.toFixed(2)}</p>
        </div>
        <div className="text-right">
          <p className="text-white font-mono">${position.current_price.toFixed(2)}</p>
          <p className="font-mono text-sm" style={{ color: pnlColor }}>
            {pnlSign}${position.unrealised_pnl.toFixed(2)} ({pnlSign}{position.unrealised_pnl_pct.toFixed(1)}%)
          </p>
        </div>
      </div>
      <div className="flex justify-between items-center mt-3">
        <span className="text-gray-400 text-xs">
          Value: ${position.market_value.toFixed(2)}
        </span>
        {onSell && (
          <button
            onClick={() => onSell(position)}
            className="bg-red-600 hover:bg-red-700 text-white text-xs px-3 py-1 rounded"
          >
            SELL
          </button>
        )}
      </div>
    </div>
  )
}
