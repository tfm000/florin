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
function bsPrice(S, K, T, r, sigma, type = 'call') {
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
