/**
 * ChartTooltip tests — D-13 mandatory cases:
 *   1. Payload extraction (named entries rendered at edge dates)
 *   2. regimeBar filter (synthetic shading key never appears in tooltip body)
 *   3. Inactive state (active=false → renders null)
 *   4. labelFormatter forwarding (custom header label rendered)
 *
 * Testing strategy: ChartTooltipBody is an internal component that recharts
 * calls by cloning the `content` element injected into <Tooltip content={...}>.
 * We extract that element from a rendered ChartTooltip instance and clone it with
 * controlled { active, payload, label } props so we can assert on its output
 * without triggering recharts mouse-event internals or depending on jsdom layout.
 *
 * The hooks (useIsTooltipActive, useActiveTooltipLabel, useActiveTooltipDataPoints)
 * are called inside ChartTooltipBody but fall back gracefully to the `active` and
 * `label` props when the recharts Redux store is absent — which is the case here
 * since we render the body element in isolation.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import React from 'react'
import { ComposedChart, Line } from 'recharts'
import { ChartTooltip } from './ChartTooltip'

/**
 * Mount ChartTooltip inside a minimal ComposedChart, extract the `content` element
 * from the rendered Tooltip, and clone it with controlled props. This approach lets
 * us test the display logic of ChartTooltipBody without simulating mouse hover events.
 *
 * @param {Object} bodyProps - Props to inject: { active, payload, label, labelFormatter, formatter }
 * @param {Object} [tooltipProps] - Additional props forwarded to <ChartTooltip>.
 * @returns {{ container: HTMLElement }} RTL render result.
 */
function renderBody(bodyProps, tooltipProps = {}) {
  // Render ChartTooltip in a real recharts tree so the hooks' Redux store context
  // is provided (avoids "called outside of chart" errors from recharts internals).
  let contentElement = null
  const fixture = [{ x: 1 }, { x: 2 }]

  function Capture() {
    const tooltip = (
      <ChartTooltip {...bodyProps} {...tooltipProps} />
    )
    // Extract the content element via React internals so we can clone it with
    // controlled props. We render the chart once to collect the element.
    contentElement = tooltip
    return (
      <ComposedChart width={400} height={300} data={fixture}>
        <Line dataKey="x" isAnimationActive={false} />
        {tooltip}
      </ComposedChart>
    )
  }

  render(<Capture />)

  // ChartTooltip renders: <Tooltip ... content={<ChartTooltipBody {...forwardedProps} />} />
  // recharts will clone the content element and inject { active, payload, label, ... }.
  // We simulate that here by rendering the content element in isolation with
  // the test's bodyProps merged in as the controlling active/payload/label.
  const tooltipEl = React.createElement(ChartTooltip, { ...bodyProps, ...tooltipProps })
  // Walk the React element tree to find the content prop set by ChartTooltip.
  // ChartTooltip passes content={<ChartTooltipBody {...props} />} to recharts Tooltip.
  // We can access that by calling the ChartTooltip function directly and extracting
  // the content prop from its returned element.
  const outerEl = ChartTooltip({ ...bodyProps, ...tooltipProps })
  const bodyContentElement = outerEl?.props?.content

  if (!bodyContentElement) {
    // Fallback: render nothing (guards unexpected API changes in recharts).
    return render(<div />)
  }

  // Clone the body element with the controlled bodyProps so active/payload/label
  // are applied and the render logic executes deterministically.
  const cloned = React.cloneElement(bodyContentElement, bodyProps)
  return render(cloned)
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TWO_SERIES_PAYLOAD = [
  { name: 'AAPL', value: 5.3, color: '#22C55E', dataKey: 'AAPL' },
  { name: 'MSFT', value: 4.1, color: '#3B82F6', dataKey: 'MSFT' },
]

const WITH_REGIME_BAR_PAYLOAD = [
  { name: 'AAPL', value: 5.3, color: '#22C55E', dataKey: 'AAPL' },
  { name: 'regimeBar', value: 1, color: '#EF4444', dataKey: 'regimeBar' },
]

const NULL_VALUE_PAYLOAD = [
  { name: 'AAPL', value: null, color: '#22C55E', dataKey: 'AAPL' },
  { name: 'MSFT', value: 4.1, color: '#3B82F6', dataKey: 'MSFT' },
]

// ---------------------------------------------------------------------------
// D-13 mandatory tests
// ---------------------------------------------------------------------------

describe('ChartTooltip — D-13 mandatory cases', () => {
  describe('1. Payload extraction at edge dates', () => {
    it('renders both series names when active and payload has two entries', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2020-03-23',
      })
      expect(container.textContent).toContain('AAPL')
      expect(container.textContent).toContain('MSFT')
    })

    it('renders the label in the tooltip header', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2020-03-23',
      })
      expect(container.textContent).toContain('2020-03-23')
    })

    it('renders entry values alongside names', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2020-03-23',
      })
      expect(container.textContent).toContain('5.3')
      expect(container.textContent).toContain('4.1')
    })
  })

  describe('2. regimeBar filter', () => {
    it('renders non-regimeBar entries and omits the regimeBar entry', () => {
      const { container } = renderBody({
        active: true,
        payload: WITH_REGIME_BAR_PAYLOAD,
        label: '2021-01-04',
      })
      expect(container.textContent).toContain('AAPL')
      expect(container.textContent).not.toContain('regimeBar')
    })
  })

  describe('3. Inactive state', () => {
    it('renders nothing when active=false', () => {
      const { container } = renderBody({
        active: false,
        payload: TWO_SERIES_PAYLOAD,
        label: '2022-06-15',
      })
      // Body should return null — container should be empty or hold no tooltip text.
      expect(container.textContent).toBe('')
    })

    it('renders nothing when payload is empty', () => {
      const { container } = renderBody({
        active: true,
        payload: [],
        label: '2022-06-15',
      })
      expect(container.textContent).toBe('')
    })

    it('renders nothing when payload is null', () => {
      const { container } = renderBody({
        active: true,
        payload: null,
        label: '2022-06-15',
      })
      expect(container.textContent).toBe('')
    })
  })

  describe('4. labelFormatter forwarding', () => {
    it('renders the formatted label when labelFormatter prop is provided', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2023-11-30',
        labelFormatter: v => `Date: ${v}`,
      })
      expect(container.textContent).toContain('Date: 2023-11-30')
    })

    it('invokes labelFormatter with (label, payload) arguments', () => {
      const calls = []
      renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2023-12-31',
        labelFormatter: (lbl, pl) => {
          calls.push({ lbl, pl })
          return `Formatted`
        },
      })
      expect(calls.length).toBeGreaterThan(0)
      expect(calls[0].lbl).toBe('2023-12-31')
      expect(calls[0].pl).toBe(TWO_SERIES_PAYLOAD)
    })
  })

  describe('5. formatter forwarding', () => {
    it('renders formatter return value instead of raw entry.value', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2024-01-15',
        formatter: (v, name) => `${name}: +${v.toFixed(1)}%`,
      })
      expect(container.textContent).toContain('+5.3%')
      expect(container.textContent).toContain('+4.1%')
    })

    it('splits a recharts [value, name] tuple instead of concatenating it', () => {
      // Regression: PriceHistoryChart's tooltipFormatter returns the recharts
      // [formattedValue, formattedName] tuple (e.g. ['$185.50', 'Price']). The
      // body must render "Price: $185.50", NOT the flattened "AAPL: $185.50Price".
      const { container } = renderBody({
        active: true,
        payload: [{ name: 'close', value: 185.5, color: '#22C55E', dataKey: 'close' }],
        label: '2024-01-15',
        formatter: (v) => [`$${v.toFixed(2)}`, 'Price'],
      })
      expect(container.textContent).toContain('Price: $185.50')
      expect(container.textContent).not.toContain('$185.50Price')
      expect(container.textContent).not.toContain('close:')
    })

    it('keeps entry.name when the formatter returns a scalar', () => {
      const { container } = renderBody({
        active: true,
        payload: [{ name: 'AAPL', value: 5.3, color: '#22C55E', dataKey: 'AAPL' }],
        label: '2024-01-15',
        formatter: (v) => `${v.toFixed(1)}%`,
      })
      expect(container.textContent).toContain('AAPL: 5.3%')
    })

    it('suppresses an entry when the formatter returns null', () => {
      const { container } = renderBody({
        active: true,
        payload: TWO_SERIES_PAYLOAD,
        label: '2024-01-15',
        formatter: (v, name) => (name === 'AAPL' ? null : [`+${v.toFixed(1)}%`, name]),
      })
      expect(container.textContent).not.toContain('AAPL')
      expect(container.textContent).toContain('MSFT: +4.1%')
    })
  })

  describe('6. null value filter', () => {
    it('omits entries where entry.value is null', () => {
      const { container } = renderBody({
        active: true,
        payload: NULL_VALUE_PAYLOAD,
        label: '2024-03-01',
      })
      // MSFT has value so it should appear; AAPL has null so it should be absent
      expect(container.textContent).toContain('MSFT')
      expect(container.textContent).not.toContain('AAPL')
    })

    it('omits the synthetic bb_range band-fill tuple', () => {
      // The Bollinger band fill Area uses dataKey="bb_range" → [lower, upper].
      // It must never surface in the tooltip as a "bb_range: 224.5,228.3" line.
      const { container } = renderBody({
        active: true,
        payload: [
          { name: 'close', value: 226.1, color: '#22C55E', dataKey: 'close' },
          { name: 'bb_range', value: [224.5, 228.3], color: '#6366F1', dataKey: 'bb_range' },
        ],
        label: '2024-03-01',
      })
      expect(container.textContent).toContain('close')
      expect(container.textContent).not.toContain('bb_range')
      expect(container.textContent).not.toContain('224.5,228.3')
    })
  })
})

// ---------------------------------------------------------------------------
// Named export shape
// ---------------------------------------------------------------------------

describe('ChartTooltip module contract', () => {
  it('exports ChartTooltip as a named function export', () => {
    expect(typeof ChartTooltip).toBe('function')
  })
})
