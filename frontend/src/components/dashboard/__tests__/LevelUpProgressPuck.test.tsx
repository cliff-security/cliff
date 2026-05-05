import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import LevelUpProgressPuck from '../LevelUpProgressPuck'

describe('<LevelUpProgressPuck />', () => {
  it('renders a check icon when a hard gate (target=0) is met', () => {
    render(<LevelUpProgressPuck current={0} target={0} />)
    const puck = screen.getByTestId('level-up-progress-puck')
    expect(puck).toHaveAttribute('data-met', 'true')
    expect(puck.textContent).toContain('check')
  })

  it('renders the remaining count when a hard gate is not met', () => {
    render(<LevelUpProgressPuck current={3} target={0} />)
    const puck = screen.getByTestId('level-up-progress-puck')
    expect(puck).toHaveAttribute('data-met', 'false')
    expect(puck).toHaveTextContent('3')
  })

  it('renders partial progress for an aggregate gate (target > 0)', () => {
    render(<LevelUpProgressPuck current={12} target={15} />)
    const puck = screen.getByTestId('level-up-progress-puck')
    expect(puck).toHaveAttribute('data-met', 'false')
    expect(puck).toHaveTextContent('3') // 15 - 12 = 3 remaining
    // Conic gradient is in the inline style.
    expect(puck.getAttribute('style')).toMatch(/conic-gradient/)
  })

  it('treats current >= target as met for aggregate gates', () => {
    render(<LevelUpProgressPuck current={15} target={15} />)
    const puck = screen.getByTestId('level-up-progress-puck')
    expect(puck).toHaveAttribute('data-met', 'true')
  })
})
