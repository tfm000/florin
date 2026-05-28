import { describe, it, expect } from 'vitest'
import { formatChartDate, formatChartDateLong } from './formatChartDate'

describe('formatChartDate — PRIM-03 UTC pinning', () => {
  it('daily date shows correct month/year regardless of process timezone', () => {
    // Previously, "new Date('2024-01-15T00:00:00')" in local TZ could shift to Jan 14 in UTC-offset zones
    expect(formatChartDate('2024-01-15')).toBe('Jan 2024')
  })

  it('does not shift Dec 31 to previous year', () => {
    expect(formatChartDate('2023-12-31')).toContain('2023')
    expect(formatChartDate('2023-12-31')).not.toContain('2022')
  })

  it('does not shift Jan 1 to previous year (east-of-UTC zone)', () => {
    expect(formatChartDate('2024-01-01')).toContain('2024')
    expect(formatChartDate('2024-01-01')).not.toContain('2023')
  })

  it('intraday mode passes through time portion', () => {
    expect(formatChartDate('2024-01-15T14:30:00', true)).toContain('14:30')
  })

  it('handles empty string without throwing', () => {
    expect(formatChartDate('')).toBe('')
  })

  it('handles null without throwing', () => {
    expect(formatChartDate(null)).toBe('')
  })

  it('date at UTC midnight not shifted by US/Eastern offset (PRIM-03 DST edge)', () => {
    // US/Eastern is UTC-5 in winter — '2024-03-10T00:00:00' local = Mar 9 UTC
    // Correct UTC-pinned result is always Mar 2024
    expect(formatChartDate('2024-03-10')).toContain('Mar')
    expect(formatChartDate('2024-03-10')).not.toContain('Feb')
  })

  it('explicit daily mode (intraday=false) behaves identically to default', () => {
    expect(formatChartDate('2024-01-15', false)).toBe('Jan 2024')
  })
})

describe('formatChartDateLong — PRIM-03 tooltip label form', () => {
  it('daily date contains day, month abbreviation, and year', () => {
    const result = formatChartDateLong('2024-01-15')
    expect(result).toContain('Jan')
    expect(result).toContain('15')
    expect(result).toContain('2024')
  })

  it('intraday mode contains the time component', () => {
    expect(formatChartDateLong('2024-01-15T14:30:00', true)).toContain('14:30')
  })

  it('handles empty string without throwing', () => {
    expect(formatChartDateLong('')).toBe('')
  })

  it('handles null without throwing', () => {
    expect(formatChartDateLong(null)).toBe('')
  })
})
