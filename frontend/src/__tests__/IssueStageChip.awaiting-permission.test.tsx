/**
 * IssueStageChip — "Awaiting approval" stage renders with the cyan tone
 * + pulse dot, matching the existing ``pr_awaiting_val`` chip visually.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IssueStageChip } from '@/components/issues/IssueStageChip'

describe('<IssueStageChip kind="awaiting_permission" />', () => {
  it('renders the "Awaiting approval" label', () => {
    render(<IssueStageChip kind="awaiting_permission" />)
    expect(
      screen.getByTestId('stage-chip-awaiting_permission'),
    ).toHaveTextContent('Awaiting approval')
  })

  it('uses the cyan chip class so it visually matches awaiting validation', () => {
    render(<IssueStageChip kind="awaiting_permission" />)
    const chip = screen.getByTestId('stage-chip-awaiting_permission')
    expect(chip.className).toContain('cd-chip')
    expect(chip.className).toContain('cd-chip--cyan')
  })
})
