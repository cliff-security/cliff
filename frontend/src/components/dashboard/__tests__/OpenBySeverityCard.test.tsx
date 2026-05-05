import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import OpenBySeverityCard from '../OpenBySeverityCard'

const FULL = [
  { kind: 'critical' as const, count: 1, weekly_delta: -1 },
  { kind: 'high' as const, count: 9, weekly_delta: -3 },
  { kind: 'medium' as const, count: 26, weekly_delta: -1 },
  { kind: 'low' as const, count: 24, weekly_delta: 0 },
]

describe('<OpenBySeverityCard />', () => {
  it('renders the total + caption + a row per severity with non-zero count', () => {
    render(<OpenBySeverityCard rows={FULL} />)
    const card = screen.getByTestId('open-by-severity-card')
    expect(card).toHaveTextContent('60') // total
    expect(card).toHaveTextContent('across 4 severities')

    for (const r of FULL) {
      expect(
        screen.getByTestId(`open-by-severity-row-${r.kind}`),
      ).toBeInTheDocument()
    }
  })

  it('zero-state shows the "nothing open" copy and no severity bar', () => {
    render(
      <OpenBySeverityCard
        rows={[
          { kind: 'critical', count: 0, weekly_delta: 0 },
          { kind: 'high', count: 0, weekly_delta: 0 },
          { kind: 'medium', count: 0, weekly_delta: 0 },
          { kind: 'low', count: 0, weekly_delta: 0 },
        ]}
      />,
    )
    expect(screen.getByText(/Nothing open/i)).toBeInTheDocument()
    expect(screen.queryByTestId('severity-bar')).toBeNull()
  })

  it('clicking a row triggers onSelectSeverity', () => {
    const onSelectSeverity = vi.fn()
    render(
      <OpenBySeverityCard rows={FULL} onSelectSeverity={onSelectSeverity} />,
    )
    fireEvent.click(screen.getByTestId('open-by-severity-row-high'))
    expect(onSelectSeverity).toHaveBeenCalledWith('high')
  })

  it('segment widths sum to ~100% (allowing for rendering rounding)', () => {
    render(<OpenBySeverityCard rows={FULL} />)
    const segments = [
      'severity-bar-critical',
      'severity-bar-high',
      'severity-bar-medium',
      'severity-bar-low',
    ].map((id) => screen.getByTestId(id))

    const widths = segments
      .map((el) => el.getAttribute('style') || '')
      .map((style) => {
        const m = /width:\s*([\d.]+)%/.exec(style)
        return m ? parseFloat(m[1]) : 0
      })

    const total = widths.reduce((acc, w) => acc + w, 0)
    expect(total).toBeGreaterThan(99)
    expect(total).toBeLessThan(101)
  })
})
