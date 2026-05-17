import { describe, it, expect } from 'vitest'
import { HISTORICAL_PERIODS } from './periods'
import { buildRegimeQuery } from './regimeQuery'

describe('buildRegimeQuery — FND-03 / TEST-02', () => {
  describe('ticker-based regime URL (asset-research style)', () => {
    it.each(HISTORICAL_PERIODS)('builds a /regime/{ticker} URL for period=%s', (period) => {
      const { url, meta } = buildRegimeQuery({
        ticker: 'AAPL',
        period,
        nRegimes: 2,
        interval: '1d',
      })
      expect(url).toBe(`/regime/AAPL?n_regimes=2&interval=1d&period=${period}`)
      expect(meta).toEqual({ effectivePeriod: period, interval: '1d', nRegimes: 2 })
    })

    it('appends source when provided', () => {
      const { url } = buildRegimeQuery({
        ticker: 'AAPL',
        period: '1y',
        nRegimes: 3,
        interval: '1d',
        source: 'SPY',
      })
      expect(url).toBe('/regime/AAPL?n_regimes=3&interval=1d&source=SPY&period=1y')
    })

    it('uses start/end on custom range', () => {
      const { url, meta } = buildRegimeQuery({
        ticker: 'AAPL',
        customStart: '2024-01-01',
        customEnd: '2024-12-31',
        nRegimes: 2,
        interval: '1d',
      })
      expect(url).toBe(
        '/regime/AAPL?n_regimes=2&interval=1d&start=2024-01-01&end=2024-12-31',
      )
      expect(meta.effectivePeriod).toBe('custom')
    })
  })

  describe('portfolio-based regime URL', () => {
    it.each(HISTORICAL_PERIODS)('builds a /portfolios/{id}/regime URL for period=%s', (period) => {
      const { url } = buildRegimeQuery({ portfolioId: 7, period, nRegimes: 2 })
      expect(url).toBe(`/portfolios/7/regime?n_regimes=2&period=${period}`)
    })

    it('uses start/end on custom range', () => {
      const { url } = buildRegimeQuery({
        portfolioId: 7,
        customStart: '2024-01-01',
        customEnd: '2024-12-31',
        nRegimes: 2,
      })
      expect(url).toBe(
        '/portfolios/7/regime?n_regimes=2&start=2024-01-01&end=2024-12-31',
      )
    })
  })

  describe('input validation', () => {
    it('throws when neither ticker nor portfolioId is provided', () => {
      expect(() => buildRegimeQuery({ period: '1y', nRegimes: 2 })).toThrow(/either ticker/)
    })

    it('throws when both ticker and portfolioId are provided', () => {
      expect(() =>
        buildRegimeQuery({ ticker: 'AAPL', portfolioId: 7, period: '1y', nRegimes: 2 }),
      ).toThrow(/either ticker/)
    })
  })

  describe('BUG-01 regression — 3y and 5y produce the expected URLs', () => {
    it('3y emits period=3y for ticker variant', () => {
      const { url } = buildRegimeQuery({ ticker: 'AAPL', period: '3y', nRegimes: 2, interval: '1d' })
      expect(url).toBe('/regime/AAPL?n_regimes=2&interval=1d&period=3y')
    })

    it('5y emits period=5y for portfolio variant', () => {
      const { url } = buildRegimeQuery({ portfolioId: 7, period: '5y', nRegimes: 2 })
      expect(url).toBe('/portfolios/7/regime?n_regimes=2&period=5y')
    })
  })
})
