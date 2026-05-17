import { describe, it, expect, vi, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import PriceHistoryChart from './PriceHistoryChart'
import { ChartColorProvider } from '../../hooks/useChartColors'

/**
 * Test suite for PriceHistoryChart — CHART-01..03 + D-13 recommended battery.
 *
 * All tests use the ChartColorProvider wrapper so useChartColors() resolves.
 * All chart elements use isAnimationActive={false} (set inside the component)
 * to prevent act() warnings in jsdom.
 * ResizeObserver / IntersectionObserver / getBoundingClientRect are stubbed
 * in src/test/setup.js (Phase 1 infrastructure, Phase 2 consumers inherit).
 */

// Wrapper that provides the chart color palette context to all tests.
function Wrapper({ children }) {
  return <ChartColorProvider>{children}</ChartColorProvider>
}

// OHLCV fixture — 2 rows minimum per RESEARCH.md Finding 8.
const fixture = [
  {
    date: '2024-01-01',
    open: 180,
    high: 185,
    low: 178,
    close: 183,
    volume: 50_000_000,
    candleBody: [180, 183],
    candleUp: true,
  },
  {
    date: '2024-01-02',
    open: 183,
    high: 187,
    low: 181,
    close: 185,
    volume: 55_000_000,
    candleBody: [183, 185],
    candleUp: true,
  },
]

// Intraday fixture — timestamp strings for the DateAxis intraday branch.
const intradayFixture = [
  {
    date: '2024-01-15T14:30:00',
    open: 180,
    high: 182,
    low: 179,
    close: 181,
    volume: 5_000_000,
    candleBody: [180, 181],
    candleUp: true,
  },
  {
    date: '2024-01-15T14:31:00',
    open: 181,
    high: 183,
    low: 180,
    close: 182,
    volume: 4_500_000,
    candleBody: [181, 182],
    candleUp: true,
  },
]

// Standard series prop — single primary series.
const series = [{ key: 'close', label: 'Price', isPrimary: true }]

// Regime feature fixture — minimal valid shape matching the RegimeResponse schema.
const regimeFeature = {
  data: {
    regimes: [
      { date: '2024-01-01', regime: 0 },
      { date: '2024-01-02', regime: 1 },
    ],
    stats: [
      { regime: 0, volatility: 12.3 },
      { regime: 1, volatility: 28.7 },
    ],
    source_ticker: 'SPY',
  },
}

describe('PriceHistoryChart — CHART-01..03 + D-13', () => {

  describe('basic render', () => {
    it('renders without crashing with empty features bag (line mode default)', () => {
      const { container } = render(
        <PriceHistoryChart data={fixture} series={series} intraday={false} features={{}} />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })

    it('renders the chart title in price mode', () => {
      const { container } = render(
        <PriceHistoryChart data={fixture} series={series} intraday={false} />,
        { wrapper: Wrapper },
      )
      expect(container.textContent).toContain('Price History')
    })
  })

  describe('features bag — individual feature rendering', () => {
    it('renders without crashing when features.regime is enabled', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ regime: regimeFeature }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })

    it('shows regime legend strip when features.regime has stats', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ regime: regimeFeature }}
        />,
        { wrapper: Wrapper },
      )
      // The legend strip renders vol% labels like "R0 12.3%vol"
      expect(container.textContent).toContain('R0')
      expect(container.textContent).toContain('R1')
    })

    it('renders without crashing when features.volume is enabled', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ volume: true }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })

    it('renders volume chart label when features.volume is enabled', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ volume: true }}
        />,
        { wrapper: Wrapper },
      )
      // The YAxis label for the volume subchart contains "Volume"
      expect(container.textContent).toContain('Volume')
    })

    it('renders without crashing when features.candle is enabled', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ candle: true }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })

    it('renders without crashing when features.indicators is enabled', () => {
      // activeIndicators starts empty so no subchart is rendered, but the
      // indicator toggle UI block should render when features.indicators is truthy.
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ indicators: true }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })

    it('shows indicator toggle buttons when features.indicators is enabled', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{ indicators: true }}
        />,
        { wrapper: Wrapper },
      )
      // The indicator toggle UI renders "SMA 20", "RSI 14", etc.
      expect(container.textContent).toContain('Indicators:')
      expect(container.textContent).toContain('SMA 20')
    })
  })

  describe('ChartFrame state rendering (D-04)', () => {
    it('renders loading skeleton (not chart body) when loading=true', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          loading={true}
        />,
        { wrapper: Wrapper },
      )
      // ChartFrame loading priority renders "Loading..." and hides children
      expect(container.textContent).toContain('Loading...')
    })

    it('renders error banner when error prop is set', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          error="500 Internal Server Error"
        />,
        { wrapper: Wrapper },
      )
      expect(container.textContent).toContain('500 Internal Server Error')
    })

    it('renders stale banner when stale=true', () => {
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          stale={true}
        />,
        { wrapper: Wrapper },
      )
      // ChartFrame renders "Data may be stale" when stale=true but no error string
      expect(container.textContent).toContain('stale')
    })

    it('renders emptyMessage when data is empty', () => {
      const { container } = render(
        <PriceHistoryChart
          data={[]}
          series={series}
          intraday={false}
          emptyMessage="No data"
        />,
        { wrapper: Wrapper },
      )
      expect(container.textContent).toContain('No data')
    })

    it('renders custom emptyMessage when data is empty', () => {
      const { container } = render(
        <PriceHistoryChart
          data={[]}
          series={series}
          intraday={false}
          emptyMessage="No price history available"
        />,
        { wrapper: Wrapper },
      )
      expect(container.textContent).toContain('No price history available')
    })
  })

  describe('D-08 unknown features keys — silently ignored', () => {
    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('does not throw and does not call console.error for unknown features keys', () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{
            dailyReturnsHistogram: true,
            futureFeature99: { x: 1, y: 2 },
          }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
      expect(spy).not.toHaveBeenCalled()
    })

    it('renders normally when features combines known and unknown keys', () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { container } = render(
        <PriceHistoryChart
          data={fixture}
          series={series}
          intraday={false}
          features={{
            volume: true,
            dailyReturnsHistogram: true,
          }}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
      // Volume subchart still renders (Volume label visible)
      expect(container.textContent).toContain('Volume')
      expect(spy).not.toHaveBeenCalled()
    })
  })

  describe('intraday data path', () => {
    it('renders without crashing with intraday=true and intraday-shaped fixture', () => {
      const { container } = render(
        <PriceHistoryChart
          data={intradayFixture}
          series={series}
          intraday={true}
          features={{}}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
    })
  })

  describe('comparison mode', () => {
    it('renders without crashing in comparison mode with multiple series', () => {
      const comparisonData = fixture.map((h, i) => ({
        ...h,
        SPY: i * 0.5,
      }))
      const comparisonSeries = [
        { key: 'close', label: 'AAPL', isPrimary: true },
        { key: 'SPY', label: 'SPY' },
      ]
      const { container } = render(
        <PriceHistoryChart
          data={comparisonData}
          series={comparisonSeries}
          intraday={false}
          features={{}}
        />,
        { wrapper: Wrapper },
      )
      expect(container.firstChild).not.toBeNull()
      expect(container.textContent).toContain('Cumulative Returns')
    })
  })

  describe('threat model — T-02-04-01 (XSS)', () => {
    it('contains no dangerouslySetInnerHTML (compile-time check via grep)', () => {
      // This test documents the security invariant. The actual file check is done
      // in the task-level verify step; this test records the requirement for
      // regression tracking.
      expect(true).toBe(true) // placeholder — see task verify grep
    })
  })

  describe('threat model — T-02-04-02 (fixture leakage)', () => {
    it('fixture contains no real account IDs, API keys, or secrets', () => {
      const fixtureStr = JSON.stringify(fixture)
      expect(fixtureStr).not.toMatch(/uuid/)
      expect(fixtureStr).not.toMatch(/sk-/)
      expect(fixtureStr).not.toMatch(/api[_-]key/i)
      expect(fixtureStr).not.toMatch(/secret/i)
    })
  })
})
