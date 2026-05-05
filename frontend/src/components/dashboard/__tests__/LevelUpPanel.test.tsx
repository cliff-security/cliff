import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import LevelUpPanel, { type LevelUpPanelData } from '../LevelUpPanel'

const FIXTURE: LevelUpPanelData = {
  current: 'B',
  next: 'A',
  summary: 'Three things between you and an A. Two are one-click.',
  gates: [
    {
      id: 'criticals_open',
      label: 'Close the open Critical',
      detail: 'RCE in lodash · plan ready for your review',
      current: 1,
      target: 0,
      unit: 'critical',
      status: 'ready_to_review',
      action_label: 'Review plan',
      action_href: '/issues?open=fnd-1',
    },
    {
      id: 'posture_remaining',
      label: 'Pass remaining posture checks',
      detail: 'security_md, code_owners_exists',
      current: 12,
      target: 15,
      unit: 'posture checks',
      status: 'auto_fixable',
      action_label: 'Auto-fix 2 of 3',
      action_href: '/issues?type=posture',
      auto_fixable_check_names: ['security_md', 'code_owners_exists'],
    },
  ],
}

describe('<LevelUpPanel />', () => {
  it('renders the title with the next grade highlighted and the summary', () => {
    render(<LevelUpPanel data={FIXTURE} />)
    const panel = screen.getByTestId('level-up-panel')
    expect(panel).toHaveTextContent('Level up to')
    expect(panel).toHaveTextContent('A')
    expect(panel).toHaveTextContent(
      'Three things between you and an A. Two are one-click.',
    )
  })

  it('renders the current → next pill transition', () => {
    render(<LevelUpPanel data={FIXTURE} />)
    expect(screen.getByTestId('level-up-grade-pill-current')).toHaveTextContent(
      'B',
    )
    expect(screen.getByTestId('level-up-grade-pill-next')).toHaveTextContent('A')
  })

  it('renders one GateRow per gate', () => {
    render(<LevelUpPanel data={FIXTURE} />)
    expect(screen.getByTestId('gate-row-criticals_open')).toBeInTheDocument()
    expect(screen.getByTestId('gate-row-posture_remaining')).toBeInTheDocument()
  })

  it('shows the "hold the line" copy when there are no gates', () => {
    render(
      <LevelUpPanel
        data={{ ...FIXTURE, gates: [], summary: "You're an A. Hold the line." }}
      />,
    )
    expect(
      screen.getByText(/already meeting the bar/i),
    ).toBeInTheDocument()
  })

  it('clicking "View full rubric" fires onViewRubric', () => {
    const onViewRubric = vi.fn()
    render(<LevelUpPanel data={FIXTURE} onViewRubric={onViewRubric} />)
    fireEvent.click(screen.getByText(/View full rubric/i))
    expect(onViewRubric).toHaveBeenCalledTimes(1)
  })

  it('clicking auto_fixable gate calls onAutoFix with check names', async () => {
    const onAutoFix = vi.fn().mockResolvedValue(undefined)
    render(<LevelUpPanel data={FIXTURE} onAutoFix={onAutoFix} />)
    fireEvent.click(screen.getByTestId('gate-row-posture_remaining-action'))
    expect(onAutoFix).toHaveBeenCalledWith([
      'security_md',
      'code_owners_exists',
    ])
  })
})
