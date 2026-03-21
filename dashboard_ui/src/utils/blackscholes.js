/**
 * Black-Scholes option pricing and Greeks calculations.
 *
 * All inputs:
 *   S = spot price
 *   K = strike price
 *   T = time to expiry in years
 *   r = risk-free rate (annualized, decimal)
 *   sigma = implied volatility (decimal)
 *   type = 'call' | 'put'
 */

// Standard normal CDF (Abramowitz & Stegun approximation)
function normcdf(x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911
  const sign = x < 0 ? -1 : 1
  x = Math.abs(x) / Math.SQRT2
  const t = 1.0 / (1.0 + p * x)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x)
  return 0.5 * (1.0 + sign * y)
}

// Standard normal PDF
function normpdf(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}

function d1(S, K, T, r, sigma) {
  if (T <= 0 || sigma <= 0 || S <= 0 || K <= 0) return 0
  return (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T))
}

function d2(S, K, T, r, sigma) {
  return d1(S, K, T, r, sigma) - sigma * Math.sqrt(T)
}

/**
 * Black-Scholes option price
 */
export function bsPrice(S, K, T, r, sigma, type = 'call') {
  if (T <= 0) return Math.max(type === 'call' ? S - K : K - S, 0)
  const D1 = d1(S, K, T, r, sigma)
  const D2 = d2(S, K, T, r, sigma)
  if (type === 'call') {
    return S * normcdf(D1) - K * Math.exp(-r * T) * normcdf(D2)
  }
  return K * Math.exp(-r * T) * normcdf(-D2) - S * normcdf(-D1)
}

/**
 * Greeks
 */
export function delta(S, K, T, r, sigma, type = 'call') {
  if (T <= 0 || sigma <= 0) return type === 'call' ? (S > K ? 1 : 0) : (S < K ? -1 : 0)
  const D1 = d1(S, K, T, r, sigma)
  return type === 'call' ? normcdf(D1) : normcdf(D1) - 1
}

export function gamma(S, K, T, r, sigma) {
  if (T <= 0 || sigma <= 0 || S <= 0) return 0
  const D1 = d1(S, K, T, r, sigma)
  return normpdf(D1) / (S * sigma * Math.sqrt(T))
}

export function vega(S, K, T, r, sigma) {
  if (T <= 0 || sigma <= 0) return 0
  const D1 = d1(S, K, T, r, sigma)
  return S * normpdf(D1) * Math.sqrt(T) / 100 // per 1% change in vol
}

export function theta(S, K, T, r, sigma, type = 'call') {
  if (T <= 0 || sigma <= 0) return 0
  const D1 = d1(S, K, T, r, sigma)
  const D2 = d2(S, K, T, r, sigma)
  const common = -(S * normpdf(D1) * sigma) / (2 * Math.sqrt(T))
  if (type === 'call') {
    return (common - r * K * Math.exp(-r * T) * normcdf(D2)) / 365
  }
  return (common + r * K * Math.exp(-r * T) * normcdf(-D2)) / 365
}

export function rho(S, K, T, r, sigma, type = 'call') {
  if (T <= 0) return 0
  const D2 = d2(S, K, T, r, sigma)
  if (type === 'call') {
    return K * T * Math.exp(-r * T) * normcdf(D2) / 100
  }
  return -K * T * Math.exp(-r * T) * normcdf(-D2) / 100
}

/**
 * All Greeks at once
 */
export function allGreeks(S, K, T, r, sigma, type = 'call') {
  return {
    price: bsPrice(S, K, T, r, sigma, type),
    delta: delta(S, K, T, r, sigma, type),
    gamma: gamma(S, K, T, r, sigma),
    vega: vega(S, K, T, r, sigma),
    theta: theta(S, K, T, r, sigma, type),
    rho: rho(S, K, T, r, sigma, type),
  }
}

/**
 * Payoff at expiry for a position
 *
 * positions: Array of { type: 'call'|'put', strike, quantity, premium }
 * spotRange: Array of spot prices to compute payoff at
 *
 * Returns: Array of { spot, payoff, breakeven }
 */
export function computePayoff(positions, spotRange) {
  return spotRange.map(spot => {
    let payoff = 0
    for (const pos of positions) {
      const intrinsic = pos.type === 'call'
        ? Math.max(spot - pos.strike, 0)
        : Math.max(pos.strike - spot, 0)
      payoff += pos.quantity * (intrinsic - pos.premium)
    }
    return { spot, payoff }
  })
}

/**
 * Pre-built strategy payoffs
 */
export const STRATEGIES = {
  longCall: (strike, premium) => [{ type: 'call', strike, quantity: 1, premium }],
  longPut: (strike, premium) => [{ type: 'put', strike, quantity: 1, premium }],
  shortCall: (strike, premium) => [{ type: 'call', strike, quantity: -1, premium }],
  shortPut: (strike, premium) => [{ type: 'put', strike, quantity: -1, premium }],
  coveredCall: (entryPrice, strike, premium) => [
    { type: 'call', strike, quantity: -1, premium },
    { type: 'call', strike: 0, quantity: 1, premium: entryPrice }, // synthetic stock
  ],
  bullCallSpread: (lowStrike, highStrike, lowPrem, highPrem) => [
    { type: 'call', strike: lowStrike, quantity: 1, premium: lowPrem },
    { type: 'call', strike: highStrike, quantity: -1, premium: highPrem },
  ],
  bearPutSpread: (lowStrike, highStrike, lowPrem, highPrem) => [
    { type: 'put', strike: highStrike, quantity: 1, premium: highPrem },
    { type: 'put', strike: lowStrike, quantity: -1, premium: lowPrem },
  ],
  straddle: (strike, callPrem, putPrem) => [
    { type: 'call', strike, quantity: 1, premium: callPrem },
    { type: 'put', strike, quantity: 1, premium: putPrem },
  ],
}

/**
 * Generate spot range for payoff diagrams
 */
export function spotRange(center, width = 0.3, steps = 100) {
  const low = center * (1 - width)
  const high = center * (1 + width)
  const step = (high - low) / steps
  return Array.from({ length: steps + 1 }, (_, i) => Math.round((low + i * step) * 100) / 100)
}
