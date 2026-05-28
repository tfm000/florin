import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ChartFrame } from './ChartFrame'

describe('ChartFrame - PRIM-04', () => {
  it('renders loading skeleton when loading=true and hides children', () => {
    const { container } = render(
      <ChartFrame loading={true}>
        <div>child content</div>
      </ChartFrame>,
    )
    // Loading skeleton must have animate-pulse class
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    // Children must NOT be visible during loading
    expect(container.textContent).not.toContain('child content')
  })

  it('renders error banner showing error string when both stale=true and error is set', () => {
    const { container } = render(
      <ChartFrame stale={true} error="500 Internal Server Error">
        <div>chart data</div>
      </ChartFrame>,
    )
    expect(container.textContent).toContain('500 Internal Server Error')
    // Children should not be rendered in error state
    expect(container.textContent).not.toContain('chart data')
  })

  it('renders error banner when only error is set (stale unset)', () => {
    const { container } = render(
      <ChartFrame error="Network down">
        <div>chart data</div>
      </ChartFrame>,
    )
    expect(container.textContent).toContain('Network down')
    expect(container.textContent).not.toContain('chart data')
  })

  it('renders emptyMessage when empty=true and no other flags set', () => {
    const { container } = render(
      <ChartFrame empty={true} emptyMessage="No data available">
        <div>chart data</div>
      </ChartFrame>,
    )
    expect(container.textContent).toContain('No data available')
    expect(container.textContent).not.toContain('chart data')
  })

  it('renders children when all flags are false', () => {
    const { container } = render(
      <ChartFrame>
        <div>actual chart</div>
      </ChartFrame>,
    )
    expect(container.textContent).toContain('actual chart')
    expect(container.querySelector('.animate-pulse')).toBeFalsy()
  })

  it('loading wins over error in render priority (loading=true + error set -> skeleton, no error string)', () => {
    const { container } = render(
      <ChartFrame loading={true} error="Some error">
        <div>chart</div>
      </ChartFrame>,
    )
    // Loading skeleton should be present
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    // Error string must NOT appear when loading wins
    expect(container.textContent).not.toContain('Some error')
  })
})
