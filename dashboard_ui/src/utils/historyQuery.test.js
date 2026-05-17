import { describe, it, expect } from 'vitest'
import { HISTORICAL_PERIODS, INTRADAY_PERIODS, INTRADAY_TO_HISTORY } from './periods'
import { buildHistoryQuery } from './historyQuery'

describe('buildHistoryQuery — FND-02 / TEST-02', () => {
  describe('historical periods (every token in the canonical vocabulary)', () => {
    it.each(HISTORICAL_PERIODS)('builds a daily-interval URL for period=%s', (period) => {
      const { url, meta } = buildHistoryQuery({ ticker: 'AAPL', period })
      expect(url).toBe(`/research/asset/AAPL/history?period=${period}&interval=1d`)
      expect(meta).toEqual({ interval: '1d', effectivePeriod: period })
    })
  })

  describe('intraday periods (mapped to yfinance-compatible period+interval)', () => {
    it.each(INTRADAY_PERIODS)('maps intraday key=%s via INTRADAY_TO_HISTORY', (key) => {
      const mapped = INTRADAY_TO_HISTORY[key]
      const { url, meta } = buildHistoryQuery({ ticker: 'AAPL', period: key })
      expect(url).toBe(
        `/research/asset/AAPL/history?period=${mapped.period}&interval=${mapped.interval}`,
      )
      expect(meta).toEqual({ interval: mapped.interval, effectivePeriod: mapped.period })
    })
  })

  describe('custom range', () => {
    it('uses start/end + default daily interval when customStart and customEnd are set', () => {
      const { url, meta } = buildHistoryQuery({
        ticker: 'AAPL',
        period: '3y',
        customStart: '2024-01-01',
        customEnd: '2024-12-31',
      })
      expect(url).toBe(
        '/research/asset/AAPL/history?start=2024-01-01&end=2024-12-31&interval=1d',
      )
      expect(meta).toEqual({ interval: '1d', effectivePeriod: 'custom' })
    })

    it('honors caller-provided interval in custom range', () => {
      const { url, meta } = buildHistoryQuery({
        ticker: 'AAPL',
        period: '3y',
        customStart: '2024-01-01',
        customEnd: '2024-12-31',
        interval: '1wk',
      })
      expect(url).toBe(
        '/research/asset/AAPL/history?start=2024-01-01&end=2024-12-31&interval=1wk',
      )
      expect(meta.interval).toBe('1wk')
    })
  })

  describe('BUG-01 regression — 3y and 5y produce the expected URLs', () => {
    it('3y emits period=3y', () => {
      const { url } = buildHistoryQuery({ ticker: 'AAPL', period: '3y' })
      expect(url).toBe('/research/asset/AAPL/history?period=3y&interval=1d')
    })

    it('5y emits period=5y', () => {
      const { url } = buildHistoryQuery({ ticker: 'AAPL', period: '5y' })
      expect(url).toBe('/research/asset/AAPL/history?period=5y&interval=1d')
    })
  })

  describe('adjusted flag', () => {
    it('omits adjusted= when adjusted=true (default)', () => {
      const { url } = buildHistoryQuery({ ticker: 'AAPL', period: '1y' })
      expect(url).not.toContain('adjusted=')
    })

    it('appends adjusted=false when adjusted=false (DataDownload unadjusted-export path)', () => {
      const { url } = buildHistoryQuery({ ticker: 'AAPL', period: '1y', adjusted: false })
      expect(url).toBe('/research/asset/AAPL/history?period=1y&interval=1d&adjusted=false')
    })
  })
})
