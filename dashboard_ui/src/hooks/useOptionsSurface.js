import { useApi } from './useApi'

/**
 * Single-expiry options surface — runs SSVI/SABR + GP + RND for one slice.
 *
 * @param {string} ticker
 * @param {string|null} expiry  YYYY-MM-DD, or null for auto-select.
 * @param {object} opts  { model: 'ssvi' | 'sabr', enabled: boolean }
 */
export function useOptionsSurface(ticker, expiry, { model = 'ssvi', enabled = true } = {}) {
  const exp = expiry ? `&expiry=${expiry}` : ''
  const path = enabled && ticker ? `/options/surface?ticker=${ticker}${exp}&model=${model}` : null
  return useApi(path, { autoFetch: enabled })
}

/**
 * Multi-expiry surface. Heavier — fetched only when overlay/3D view is active.
 */
export function useOptionsSurfaceMulti(ticker, { model = 'ssvi', nExpiries = 8, enabled = true } = {}) {
  const path =
    enabled && ticker
      ? `/options/surface/multi?ticker=${ticker}&model=${model}&n_expiries=${nExpiries}`
      : null
  return useApi(path, { autoFetch: enabled })
}

/**
 * Per-expiry ATM put-call IV spread (lightweight; no fitting).
 */
export function useOptionsSpreadCurve(ticker, { enabled = true } = {}) {
  const path = enabled && ticker ? `/options/spread-curve?ticker=${ticker}` : null
  return useApi(path, { autoFetch: enabled })
}
