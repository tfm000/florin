import { describe, it, expect } from 'vitest'
import { buildIntradayQuery } from './intradayQuery'

describe('buildIntradayQuery', () => {
  it('builds the Alpaca quotes/intraday URL with the given interval', () => {
    const { url } = buildIntradayQuery({ ticker: 'AAPL', interval: '5Min' })
    expect(url).toBe('/research/asset/AAPL/quotes/intraday?interval=5Min')
  })

  it('defaults interval to 5Min', () => {
    expect(buildIntradayQuery({ ticker: 'MSFT' }).url).toBe(
      '/research/asset/MSFT/quotes/intraday?interval=5Min',
    )
  })

  it('preserves dot-class tickers (BRK.B)', () => {
    expect(buildIntradayQuery({ ticker: 'BRK.B', interval: '1Min' }).url).toBe(
      '/research/asset/BRK.B/quotes/intraday?interval=1Min',
    )
  })

  it('exposes meta with effectivePeriod "intraday"', () => {
    expect(buildIntradayQuery({ ticker: 'AAPL', interval: '15Min' }).meta).toEqual({
      interval: '15Min',
      effectivePeriod: 'intraday',
    })
  })

  it.each(['1Min', '5Min', '15Min', '30Min', '1Hour'])(
    'supports every intraday interval (%s)',
    (iv) => {
      expect(buildIntradayQuery({ ticker: 'AAPL', interval: iv }).url).toContain(`interval=${iv}`)
    },
  )
})
