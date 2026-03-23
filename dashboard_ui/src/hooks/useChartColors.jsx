import { createContext, useContext, useState, useEffect } from 'react'

/**
 * Chart color palette context.
 *
 * Default: standard palette (green/red for gain/loss)
 * Colorblind mode: blue/orange palette safe for deuteranopia/protanopia
 */

const PALETTES = {
  standard: {
    positive: '#22C55E',    // green — gains, good ratios, low risk
    negative: '#EF4444',    // red — losses, bad ratios, high risk
    warning: '#EAB308',     // yellow — medium risk, caution
    neutral: '#9CA3AF',     // gray — no signal
    series: ['#22C55E', '#6366F1', '#F59E0B', '#EF4444', '#EC4899'],
    regime: ['#22C55E', '#EF4444', '#F59E0B'],  // low vol (green), high vol (red), mid (amber)
    putIv: '#EF4444',       // red
    callIv: '#22C55E',      // green
    compositeVol: '#8B5CF6', // purple
    atm: '#F59E0B',         // amber
  },
  colorblind: {
    positive: '#2563EB',    // blue — gains, good ratios, low risk
    negative: '#EF4444',    // red — losses, bad ratios, high risk
    warning: '#F59E0B',     // amber — medium risk, caution
    neutral: '#9CA3AF',     // gray — no signal
    series: ['#2563EB', '#14B8A6', '#F59E0B', '#EF4444', '#EC4899'],
    regime: ['#2563EB', '#EF4444', '#F59E0B'],  // low vol (blue), high vol (red), mid (amber)
    putIv: '#EF4444',       // red
    callIv: '#2563EB',      // blue
    compositeVol: '#14B8A6', // teal (distinct from blue)
    atm: '#F59E0B',         // amber
  },
}

const ChartColorContext = createContext(PALETTES.standard)
const ColorblindToggleContext = createContext(() => {})
const IsColorblindContext = createContext(false)

export function ChartColorProvider({ children }) {
  const [colorblind, setColorblind] = useState(() => {
    try { return localStorage.getItem('colorblind_mode') === 'true' } catch { return false }
  })

  useEffect(() => {
    try { localStorage.setItem('colorblind_mode', String(colorblind)) } catch {}
  }, [colorblind])

  const palette = colorblind ? PALETTES.colorblind : PALETTES.standard

  return (
    <IsColorblindContext.Provider value={colorblind}>
      <ColorblindToggleContext.Provider value={setColorblind}>
        <ChartColorContext.Provider value={palette}>
          {children}
        </ChartColorContext.Provider>
      </ColorblindToggleContext.Provider>
    </IsColorblindContext.Provider>
  )
}

export function useChartColors() {
  return useContext(ChartColorContext)
}

export function useColorblindToggle() {
  return [useContext(IsColorblindContext), useContext(ColorblindToggleContext)]
}
