import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export default function YieldCurveChart({ data, region = 'US' }) {
  if (!data || !data.curve) return null

  const tenors = ['3M', '2Y', '5Y', '10Y', '30Y']
  const chartData = tenors
    .filter(t => data.curve[t] != null)
    .map(t => ({ tenor: t, yield: data.curve[t] }))

  if (chartData.length === 0) return <p className="text-gray-500 text-sm">No yield data available</p>

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">{region} Yield Curve</h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="tenor" tick={{ fill: '#9CA3AF', fontSize: 12 }} />
          <YAxis tick={{ fill: '#9CA3AF', fontSize: 12 }} domain={['auto', 'auto']} tickFormatter={v => `${v}%`} />
          <Tooltip
            contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#fff' }}
            formatter={(v) => [`${v.toFixed(3)}%`, 'Yield']}
          />
          <Line type="monotone" dataKey="yield" stroke="#6366F1" strokeWidth={2} dot={{ fill: '#6366F1', r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
