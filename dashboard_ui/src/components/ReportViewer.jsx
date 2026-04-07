const RECOMMENDATION_COLORS = {
  STRONG_BUY: 'text-green-400 bg-green-900/30',
  BUY: 'text-green-300 bg-green-900/20',
  HOLD: 'text-yellow-300 bg-yellow-900/20',
  AVOID: 'text-red-300 bg-red-900/20',
  STRONG_AVOID: 'text-red-400 bg-red-900/30',
}

const FRAUD_COLORS = {
  LOW: 'text-green-400',
  MEDIUM: 'text-yellow-400',
  HIGH: 'text-orange-400',
  CRITICAL: 'text-red-400',
}

export default function ReportViewer({ report }) {
  if (!report) return null

  const recClass = RECOMMENDATION_COLORS[report.final_recommendation] || 'text-gray-300'
  const fraudClass = FRAUD_COLORS[report.fraud_risk_level] || 'text-gray-400'

  return (
    <div className="bg-gray-800 rounded-lg p-5 border border-gray-700 space-y-4">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h3 className="text-white font-bold text-xl">{report.ticker}</h3>
          <p className="text-gray-400 text-sm">
            ${report.alert_price.toFixed(2)} | {report.alert_change_pct > 0 ? '+' : ''}{report.alert_change_pct.toFixed(1)}% | Mode: {report.mode}
          </p>
        </div>
        <span className={`px-3 py-1 rounded-full text-sm font-bold ${recClass}`}>
          {report.final_recommendation}
        </span>
      </div>

      {/* Scores */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-gray-900 rounded p-3 text-center">
          <p className="text-gray-400 text-xs">Score</p>
          <p className="text-white font-mono text-lg">{report.final_score.toFixed(1)}</p>
        </div>
        <div className="bg-gray-900 rounded p-3 text-center">
          <p className="text-gray-400 text-xs">Confidence</p>
          <p className="text-white font-mono text-lg">{(report.final_confidence * 100).toFixed(0)}%</p>
        </div>
        <div className="bg-gray-900 rounded p-3 text-center">
          <p className="text-gray-400 text-xs">Fraud Risk</p>
          <p className={`font-mono text-lg ${fraudClass}`}>{report.fraud_risk_level}</p>
        </div>
      </div>

      {/* Sentiment Sources */}
      <div>
        <h4 className="text-gray-400 text-xs uppercase mb-2">Sentiment Sources</h4>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="bg-gray-900 px-2 py-1 rounded text-gray-300">Reddit: {report.reddit_mentions}</span>
          {report.apewisdom_mentions > 0 && <span className="bg-gray-900 px-2 py-1 rounded text-purple-300">ApeWisdom: {report.apewisdom_mentions}</span>}
          {report.alphavantage_sentiment != null && <span className={`bg-gray-900 px-2 py-1 rounded ${report.alphavantage_sentiment > 0 ? 'text-green-300' : report.alphavantage_sentiment < 0 ? 'text-red-300' : 'text-gray-300'}`}>AV Sent: {report.alphavantage_sentiment?.toFixed(2)}</span>}
          <span className="bg-gray-900 px-2 py-1 rounded text-gray-300">Insider Buy: {report.insider_buys}</span>
          <span className="bg-gray-900 px-2 py-1 rounded text-gray-300">Insider Sell: {report.insider_sells}</span>
          <span className="bg-gray-900 px-2 py-1 rounded text-gray-300">News: {report.news_count}</span>
        </div>
      </div>

      {/* Fraud Flags */}
      {report.fraud_flags && report.fraud_flags.length > 0 && (
        <div>
          <h4 className="text-gray-400 text-xs uppercase mb-2">Fraud Flags</h4>
          <ul className="text-xs text-orange-300 space-y-1">
            {report.fraud_flags.map((flag, i) => (
              <li key={i}>&#9888; {flag}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-gray-500 text-xs">{report.generated_at}</p>
    </div>
  )
}
