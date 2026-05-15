import { Suspense, useMemo } from 'react'
import { useChartColors } from '../../hooks/useChartColors'
import Plot from './plotlyLazy'
import { pctMoneyness } from './moneynessUtil'

/**
 * IV curve view — Plotly line chart of hybrid SABR/SSVI + GP IV with
 * optional 68/90 credible-interval ribbons and a market-IV scatter.
 *
 * X axis: percent moneyness ``(K/F − 1) × 100``. **The shared
 * RND-derived ``xRange`` prop is intentionally ignored here** — the
 * IV smile curvature is the whole point of this view, and the
 * RND-mass-derived crop typically narrows to ±5–7 % on short-DTE
 * chains which flattens the visible curve. We always show the full
 * ±15 % window; the default math grid covers ±50 % so every
 * point in this range is a finite parametric IV.
 */
// eslint-disable-next-line no-unused-vars
export default function IVCurveView({ data, spot, F, gpBand, xRange }) {
  const IV_RANGE = [-15, 15] // hard-fixed; see component docstring
  const colors = useChartColors()

  const traces = useMemo(() => {
    if (!data || data.length === 0 || !F) return []
    const mny = data.map(p => pctMoneyness(p.strike, F))
    const strikes = data.map(p => p.strike)
    const hybrid = data.map(p => p.iv_hybrid * 100) // to %
    const parametric = data.map(p => p.iv_parametric * 100)

    const traceList = []
    if (gpBand) {
      traceList.push({
        x: mny,
        y: data.map(p => (p.iv_hi90 ?? p.iv_hybrid) * 100),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
      })
      traceList.push({
        x: mny,
        y: data.map(p => (p.iv_lo90 ?? p.iv_hybrid) * 100),
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
        y: data.map(p => (p.iv_hi68 ?? p.iv_hybrid) * 100),
        type: 'scatter',
        mode: 'lines',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
      })
      traceList.push({
        x: mny,
        y: data.map(p => (p.iv_lo68 ?? p.iv_hybrid) * 100),
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
      y: hybrid,
      type: 'scatter',
      mode: 'lines',
      line: { color: colors.compositeVol, width: 2.5 },
      name: 'Hybrid (parametric + GP)',
      customdata: strikes,
      hovertemplate:
        '<b>%{x:.2f}%</b> (K=$%{customdata:.2f})<br>IV=%{y:.2f}%<extra></extra>',
    })
    traceList.push({
      x: mny,
      y: parametric,
      type: 'scatter',
      mode: 'lines',
      line: { color: colors.atm, width: 1.5, dash: 'dot' },
      name: 'Parametric',
      customdata: strikes,
      hovertemplate:
        '<b>%{x:.2f}%</b> (K=$%{customdata:.2f})<br>σ_param=%{y:.2f}%<extra></extra>',
    })

    // Market scatter (where iv_market is non-null).
    const marketMny = []
    const marketStrike = []
    const marketIV = []
    for (const p of data) {
      if (p.iv_market != null) {
        marketMny.push(pctMoneyness(p.strike, F))
        marketStrike.push(p.strike)
        marketIV.push(p.iv_market * 100)
      }
    }
    if (marketMny.length > 0) {
      traceList.push({
        x: marketMny,
        y: marketIV,
        type: 'scatter',
        mode: 'markers',
        marker: { color: colors.callIv, size: 6, symbol: 'circle-open' },
        name: 'Market',
        customdata: marketStrike,
        hovertemplate:
          '<b>%{x:.2f}%</b> (K=$%{customdata:.2f})<br>Market IV=%{y:.2f}%<extra></extra>',
      })
    }
    return traceList
  }, [data, gpBand, colors, F])

  const spotPct = useMemo(() => {
    if (!F || !spot) return null
    const p = pctMoneyness(spot, F)
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
        range: IV_RANGE,
      },
      yaxis: {
        title: { text: 'Implied volatility (%)', font: { size: 11 } },
        gridcolor: '#374151',
        ticksuffix: '%',
      },
      shapes: [
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
      legend: { orientation: 'h', x: 1, xanchor: 'right', y: 1.05, yanchor: 'bottom' },
      hovermode: 'x unified',
    }),
    [spotPct]
  )

  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-sm text-center py-8">No IV data.</p>
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
