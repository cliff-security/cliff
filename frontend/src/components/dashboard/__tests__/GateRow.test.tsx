import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import GateRow, { type GateRowData } from '../GateRow'

function makeGate(overrides: Partial<GateRowData> = {}): GateRowData {
  return {
    id: 'criticals_open',
    label: 'Close the open Critical',
    detail: 'RCE in lodash · plan ready for your review',
    current: 1,
    target: 0,
    unit: 'critical',
    status: 'ready_to_review',
    action_label: 'Review plan',
    action_href: '/issues?open=fnd-1',
    auto_fixable_check_names: [],
    ...overrides,
  }
}

describe('<GateRow />', () => {
  it('renders the label, detail, status chip, and metric line', () => {
    render(<GateRow gate={makeGate()} />)
    const row = screen.getByTestId('gate-row-criticals_open')
    expect(row).toHaveTextContent('Close the open Critical')
    expect(row).toHaveTextContent('plan ready for your review')
    expect(row).toHaveTextContent('Ready')
    expect(row).toHaveTextContent('1 → 0')
    expect(row).toHaveTextContent('critical')
  })

  it('formats posture-style metric line with N / M passing', () => {
    render(
      <GateRow
        gate={makeGate({
          id: 'posture_remaining',
          label: 'Pass remaining posture checks',
          target: 15,
          current: 12,
          unit: 'posture checks',
          status: 'auto_fixable',
          action_label: 'Auto-fix 2 of 3',
          auto_fixable_check_names: ['security_md', 'code_owners_exists'],
        })}
      />,
    )
    expect(
      screen.getByTestId('gate-row-posture_remaining'),
    ).toHaveTextContent('12 / 15 passing')
  })

  it('navigation statuses fire onNavigate with action_href', () => {
    const onNavigate = vi.fn()
    render(<GateRow gate={makeGate()} onNavigate={onNavigate} />)
    fireEvent.click(screen.getByTestId('gate-row-criticals_open-action'))
    expect(onNavigate).toHaveBeenCalledWith('/issues?open=fnd-1')
  })

  // B27 — when the backend supplies an in_progress / todo deep-link
  // (``/issues?section=review&open=<id>``), the row must pass the full
  // URL through to ``onNavigate`` verbatim so the Issues page can pop
  // the side panel from the ``?open`` param.
  it('in_progress action_href with both section and open params is passed through unchanged', () => {
    const onNavigate = vi.fn()
    render(
      <GateRow
        gate={makeGate({
          status: 'in_progress',
          action_label: 'Open Review',
          action_href: '/issues?section=review&open=fnd-7',
          first_finding_id: 'fnd-7',
        })}
        onNavigate={onNavigate}
      />,
    )
    fireEvent.click(screen.getByTestId('gate-row-criticals_open-action'))
    expect(onNavigate).toHaveBeenCalledWith(
      '/issues?section=review&open=fnd-7',
    )
  })

  it('auto_fixable status fires onAutoFix with the check names', async () => {
    const onAutoFix = vi.fn().mockResolvedValue(undefined)
    render(
      <GateRow
        gate={makeGate({
          id: 'posture_remaining',
          status: 'auto_fixable',
          target: 15,
          current: 12,
          action_label: 'Auto-fix 2 of 3',
          auto_fixable_check_names: ['security_md', 'code_owners_exists'],
        })}
        onAutoFix={onAutoFix}
      />,
    )
    fireEvent.click(screen.getByTestId('gate-row-posture_remaining-action'))
    expect(onAutoFix).toHaveBeenCalledWith([
      'security_md',
      'code_owners_exists',
    ])
  })

  it('disables the action button while pending=true', () => {
    render(<GateRow gate={makeGate()} pending />)
    const btn = screen.getByTestId(
      'gate-row-criticals_open-action',
    ) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn).toHaveTextContent('Working…')
  })
})
