import { Suspense, useMemo } from 'react'
import { useChartColors } from '../../hooks/useChartColors'
import Plot from './plotlyLazy'
import { pctMoneyness } from './moneynessUtil'

/**
 * RND view — Plotly area chart of the median density with optional
 * 68 % / 90 % credible-interval ribbons. The X axis is percent
 * moneyness ``(K / F − 1) × 100`` and is cropped to the
 * ``xRange`` window computed by the parent (so the flat-zero tails
 * past the RND's effective support are hidden).
 */
export default function RNDView({ data, spot, F, gpBand, xRange }) {
  const colors = useChartColors()
  const traces = useMemo(() => {
    if (!data || data.length === 0 || !F) return []
    const mny = data.map(p => pctMoneyness(p.strike, F))
    const strikes = data.map(p => p.strike)
    const median = data.map(p => p.density_median)
    const traceList = []
    if (gpBand) {
      traceList.push({
        x: mny,
        y: data.map(p => p.density_hi90),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
        name: 'hi90',
      })
      traceList.push({
        x: mny,
        y: data.map(p => p.density_lo90),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        fill: 'tonexty',
        fillcolor: 'rgba(99, 102, 241, 0.12)',
        showlegend: true,
        name: '90% CI',
        hoverinfo: 'skip',
      })
      traceList.push({
        x: mny,
        y: data.map(p => p.density_hi68),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
        name: 'hi68',
      })
      traceList.push({
        x: mny,
        y: data.map(p => p.density_lo68),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        fill: 'tonexty',
        fillcolor: 'rgba(99, 102, 241, 0.22)',
        showlegend: true,
        name: '68% CI',
        hoverinfo: 'skip',
      })
    }
    traceList.push({
      x: mny,
      y: median,
      type: 'scatter',
      mode: 'lines',
      line: { color: colors.compositeVol, width: 2 },
      name: 'Density',
      // customdata keeps strike around for the tooltip; %{customdata} prints it.
      customdata: strikes,
      hovertemplate:
        '<b>%{x:.2f}%</b> (K=$%{customdata:.2f})<br>q(K)=%{y:.5f}<extra></extra>',
    })
    return traceList
  }, [data, gpBand, colors, F])

  const spotPct = useMemo(() => {
    if (!F || !spot) return null
    const p = pctMoneyness(spot, F)
    // Only draw the spot line if it's far enough from F to be visible.
    return Math.abs(p) > 0.1 ? p : null
  }, [spot, F])

  const layout = useMemo(
    () => ({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#9CA3AF', size: 11 },
      margin: { l: 50, r: 20, t: 10, b: 40 },
      xaxis: {
        title: { text: 'Moneyness (K/F − 1)', font: { size: 11 } },
        gridcolor: '#374151',
        zerolinecolor: '#374151',
        ticksuffix: '%',
        range: xRange ?? undefined,
      },
      yaxis: {
        title: { text: 'Risk-neutral density q(K)', font: { size: 11 } },
        gridcolor: '#374151',
        rangemode: 'tozero',
      },
      shapes: [
        // Forward at moneyness = 0.
        {
          type: 'line',
          x0: 0,
          x1: 0,
          y0: 0,
          y1: 1,
          yref: 'paper',
          line: { color: '#F59E0B', width: 1.5, dash: 'dash' },
        },
        ...(spotPct != null
          ? [
              {
                type: 'line',
                x0: spotPct,
                x1: spotPct,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: { color: '#FFFFFF', width: 1 },
              },
            ]
          : []),
      ],
      annotations: [
        {
          x: 0,
          y: 1,
          xref: 'x',
          yref: 'paper',
          xanchor: 'left',
          yanchor: 'top',
          text: F ? ` F=$${F.toFixed(2)}` : ' F',
          font: { color: '#F59E0B', size: 10 },
          showarrow: false,
        },
      ],
      legend: { orientation: 'h', x: 1, xanchor: 'right', y: 1.05, yanchor: 'bottom' },
      hovermode: 'x unified',
    }),
    [F, spotPct, xRange]
  )

  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-sm text-center py-8">No density data.</p>
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
