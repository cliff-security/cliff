import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import GateStatusChip from '../GateStatusChip'

describe('<GateStatusChip />', () => {
  it.each([
    ['ready_to_review', 'Ready', /var\(--primary,/],
    ['pr_ready', 'PR ready', /var\(--primary,/],
    ['in_progress', 'In progress', /primary-container/],
    ['auto_fixable', 'Auto-fixable', /tertiary-container/],
    ['todo', 'Start', /surface-container-high/],
  ] as const)(
    'renders the %s variant with label %s and the right tone',
    (status, label, toneMatch) => {
      render(<GateStatusChip status={status} />)
      const chip = screen.getByTestId('gate-status-chip')
      expect(chip).toHaveAttribute('data-status', status)
      expect(chip).toHaveTextContent(label)
      expect(chip.getAttribute('style')).toMatch(toneMatch)
    },
  )
})
