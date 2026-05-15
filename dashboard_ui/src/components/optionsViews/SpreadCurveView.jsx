import { Suspense, useMemo } from 'react'
import { useChartColors } from '../../hooks/useChartColors'
import Plot from './plotlyLazy'

/**
 * ATM put-call IV spread across expiries. Bar or line layout via the
 * spread_chart toggle.
 */
export default function SpreadCurveView({ data, mode = 'bar' }) {
  const colors = useChartColors()

  const traces = useMemo(() => {
    if (!data || data.length === 0) return []
    const x = data.map(p => p.expiry)
    const callIV = data.map(p => p.call_iv * 100)
    const putIV = data.map(p => p.put_iv * 100)
    const spread = data.map(p => p.spread * 100) // pp

    if (mode === 'bar') {
      return [
        { x, y: putIV, type: 'bar', name: 'Put IV', marker: { color: colors.putIv } },
        { x, y: callIV, type: 'bar', name: 'Call IV', marker: { color: colors.callIv } },
        { x, y: spread, type: 'bar', name: 'Put−Call spread', marker: { color: '#6366F1' } },
      ]
    }
    return [
      {
        x,
        y: putIV,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Put IV',
        line: { color: colors.putIv, width: 2 },
      },
      {
        x,
        y: callIV,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Call IV',
        line: { color: colors.callIv, width: 2 },
      },
      {
        x,
        y: spread,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Put−Call spread',
        line: { color: '#6366F1', width: 2 },
        yaxis: 'y2',
      },
    ]
  }, [data, mode, colors])

  const layout = useMemo(
    () => ({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#9CA3AF', size: 11 },
      margin: { l: 50, r: 50, t: 10, b: 60 },
      barmode: 'group',
      xaxis: {
        title: { text: 'Expiry', font: { size: 11 } },
        gridcolor: '#374151',
        tickangle: -45,
      },
      yaxis: {
        title: { text: 'IV (%)', font: { size: 11 } },
        gridcolor: '#374151',
        ticksuffix: '%',
      },
      // Plotly faults on ``yaxis2: undefined`` (tries to read
      // ``.anchor``); the key must be absent in bar mode rather than
      // assigned to undefined.
      ...(mode === 'line'
        ? {
            yaxis2: {
              title: { text: 'Spread (pp)', font: { size: 11 } },
              overlaying: 'y',
              side: 'right',
              ticksuffix: 'pp',
              showgrid: false,
            },
          }
        : {}),
      legend: { orientation: 'h', x: 1, xanchor: 'right', y: 1.05, yanchor: 'bottom' },
      hovermode: 'x unified',
    }),
    [mode]
  )

  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-sm text-center py-8">No spread data.</p>
  }
  return (
    <Suspense fallback={<div className="h-80 flex items-center justify-center text-gray-500">Loading chart…</div>}>
      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: 360 }}
        useResizeHandler
      />
    </Suspense>
  )
}
