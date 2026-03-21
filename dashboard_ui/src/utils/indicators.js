/**
 * Technical indicator calculations — all computed from OHLCV data.
 *
 * Each function takes an array of {date, open, high, low, close, volume}
 * and returns an array of computed values aligned to the input.
 */

// ============================================================================
// Moving Averages
// ============================================================================

export function sma(data, period, key = 'close') {
  const result = new Array(data.length).fill(null)
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += data[j][key]
    result[i] = sum / period
  }
  return result
}

export function ema(data, period, key = 'close') {
  const result = new Array(data.length).fill(null)
  const k = 2 / (period + 1)
  // Seed with SMA
  let sum = 0
  for (let i = 0; i < period; i++) sum += data[i][key]
  result[period - 1] = sum / period
  for (let i = period; i < data.length; i++) {
    result[i] = data[i][key] * k + result[i - 1] * (1 - k)
  }
  return result
}

// ============================================================================
// Momentum
// ============================================================================

export function rsi(data, period = 14) {
  const result = new Array(data.length).fill(null)
  if (data.length < period + 1) return result

  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const change = data[i].close - data[i - 1].close
    if (change > 0) avgGain += change
    else avgLoss -= change
  }
  avgGain /= period
  avgLoss /= period

  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)

  for (let i = period + 1; i < data.length; i++) {
    const change = data[i].close - data[i - 1].close
    const gain = change > 0 ? change : 0
    const loss = change < 0 ? -change : 0
    avgGain = (avgGain * (period - 1) + gain) / period
    avgLoss = (avgLoss * (period - 1) + loss) / period
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return result
}

export function macd(data, fast = 12, slow = 26, signal = 9) {
  const emaFast = ema(data, fast)
  const emaSlow = ema(data, slow)

  const macdLine = new Array(data.length).fill(null)
  const signalLine = new Array(data.length).fill(null)
  const histogram = new Array(data.length).fill(null)

  // MACD line = fast EMA - slow EMA
  for (let i = 0; i < data.length; i++) {
    if (emaFast[i] != null && emaSlow[i] != null) {
      macdLine[i] = emaFast[i] - emaSlow[i]
    }
  }

  // Signal line = EMA of MACD line
  const k = 2 / (signal + 1)
  let firstValid = macdLine.findIndex(v => v != null)
  if (firstValid < 0) return { macdLine, signalLine, histogram }

  // Seed signal with SMA of first `signal` MACD values
  let seedEnd = firstValid + signal - 1
  if (seedEnd >= data.length) return { macdLine, signalLine, histogram }
  let sum = 0
  for (let i = firstValid; i <= seedEnd; i++) sum += macdLine[i]
  signalLine[seedEnd] = sum / signal

  for (let i = seedEnd + 1; i < data.length; i++) {
    if (macdLine[i] != null) {
      signalLine[i] = macdLine[i] * k + signalLine[i - 1] * (1 - k)
    }
  }

  // Histogram = MACD - Signal
  for (let i = 0; i < data.length; i++) {
    if (macdLine[i] != null && signalLine[i] != null) {
      histogram[i] = macdLine[i] - signalLine[i]
    }
  }

  return { macdLine, signalLine, histogram }
}

export function stochastic(data, kPeriod = 14, dPeriod = 3, smooth = 3) {
  const result = { k: new Array(data.length).fill(null), d: new Array(data.length).fill(null) }
  if (data.length < kPeriod) return result

  // Raw %K
  const rawK = new Array(data.length).fill(null)
  for (let i = kPeriod - 1; i < data.length; i++) {
    let low = Infinity, high = -Infinity
    for (let j = i - kPeriod + 1; j <= i; j++) {
      if (data[j].low < low) low = data[j].low
      if (data[j].high > high) high = data[j].high
    }
    rawK[i] = high === low ? 50 : ((data[i].close - low) / (high - low)) * 100
  }

  // Smooth %K (SMA of rawK)
  for (let i = kPeriod - 1 + smooth - 1; i < data.length; i++) {
    let sum = 0, count = 0
    for (let j = i - smooth + 1; j <= i; j++) {
      if (rawK[j] != null) { sum += rawK[j]; count++ }
    }
    if (count > 0) result.k[i] = sum / count
  }

  // %D = SMA of %K
  for (let i = 0; i < data.length; i++) {
    if (i < dPeriod - 1) continue
    let sum = 0, count = 0
    for (let j = i - dPeriod + 1; j <= i; j++) {
      if (result.k[j] != null) { sum += result.k[j]; count++ }
    }
    if (count > 0) result.d[i] = sum / count
  }

  return result
}

// ============================================================================
// Volatility
// ============================================================================

export function bollingerBands(data, period = 20, stdDev = 2) {
  const middle = sma(data, period)
  const upper = new Array(data.length).fill(null)
  const lower = new Array(data.length).fill(null)

  for (let i = period - 1; i < data.length; i++) {
    let sumSq = 0
    for (let j = i - period + 1; j <= i; j++) {
      sumSq += (data[j].close - middle[i]) ** 2
    }
    const std = Math.sqrt(sumSq / period)
    upper[i] = middle[i] + stdDev * std
    lower[i] = middle[i] - stdDev * std
  }

  return { middle, upper, lower }
}

export function atr(data, period = 14) {
  const result = new Array(data.length).fill(null)
  if (data.length < 2) return result

  // True Range
  const tr = new Array(data.length).fill(0)
  tr[0] = data[0].high - data[0].low
  for (let i = 1; i < data.length; i++) {
    tr[i] = Math.max(
      data[i].high - data[i].low,
      Math.abs(data[i].high - data[i - 1].close),
      Math.abs(data[i].low - data[i - 1].close),
    )
  }

  // ATR = Wilder's smoothing (RMA)
  let sum = 0
  for (let i = 0; i < period; i++) sum += tr[i]
  result[period - 1] = sum / period
  for (let i = period; i < data.length; i++) {
    result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
  }

  return result
}

// ============================================================================
// Volume
// ============================================================================

export function obv(data) {
  const result = new Array(data.length).fill(null)
  result[0] = data[0].volume
  for (let i = 1; i < data.length; i++) {
    if (data[i].close > data[i - 1].close) {
      result[i] = result[i - 1] + data[i].volume
    } else if (data[i].close < data[i - 1].close) {
      result[i] = result[i - 1] - data[i].volume
    } else {
      result[i] = result[i - 1]
    }
  }
  return result
}

export function vwap(data) {
  const result = new Array(data.length).fill(null)
  let cumVol = 0, cumTP = 0
  for (let i = 0; i < data.length; i++) {
    const tp = (data[i].high + data[i].low + data[i].close) / 3
    cumVol += data[i].volume
    cumTP += tp * data[i].volume
    result[i] = cumVol > 0 ? cumTP / cumVol : null
  }
  return result
}

// ============================================================================
// Indicator metadata for UI
// ============================================================================

export const INDICATOR_DEFS = {
  // Overlays (on price chart)
  sma20: { label: 'SMA 20', type: 'overlay', color: '#F59E0B', compute: d => sma(d, 20) },
  sma50: { label: 'SMA 50', type: 'overlay', color: '#8B5CF6', compute: d => sma(d, 50) },
  sma200: { label: 'SMA 200', type: 'overlay', color: '#EC4899', compute: d => sma(d, 200) },
  ema12: { label: 'EMA 12', type: 'overlay', color: '#06B6D4', compute: d => ema(d, 12) },
  ema26: { label: 'EMA 26', type: 'overlay', color: '#14B8A6', compute: d => ema(d, 26) },
  bbands: { label: 'Bollinger', type: 'overlay', color: '#6366F1', compute: d => bollingerBands(d) },
  vwap: { label: 'VWAP', type: 'overlay', color: '#D946EF', compute: d => vwap(d) },

  // Sub-charts (below price)
  rsi: { label: 'RSI 14', type: 'subchart', color: '#F59E0B', compute: d => rsi(d), range: [0, 100], lines: [30, 70] },
  stoch: { label: 'Stoch 14,3', type: 'subchart', color: '#22C55E', compute: d => stochastic(d) },
  macd: { label: 'MACD', type: 'subchart', color: '#6366F1', compute: d => macd(d) },
  atr: { label: 'ATR 14', type: 'subchart', color: '#EF4444', compute: d => atr(d) },
  obv: { label: 'OBV', type: 'subchart', color: '#8B5CF6', compute: d => obv(d) },
}
