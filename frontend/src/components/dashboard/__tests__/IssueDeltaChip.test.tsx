import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IssueDeltaChip from '../IssueDeltaChip'

describe('<IssueDeltaChip />', () => {
  it('shows trending_down + tertiary tone for a negative delta when lowerIsBetter', () => {
    render(<IssueDeltaChip pct={-12} lowerIsBetter />)
    const chip = screen.getByTestId('issue-delta-chip')
    expect(chip).toHaveTextContent('12% · 30d')
    expect(chip.textContent).toMatch(/trending_down/)
    // Tertiary-container background means the "good direction" tone.
    expect(chip.getAttribute('style')).toMatch(/tertiary-container/)
  })

  it('shows trending_up + error tone for a positive delta when lowerIsBetter', () => {
    render(<IssueDeltaChip pct={8} lowerIsBetter />)
    const chip = screen.getByTestId('issue-delta-chip')
    expect(chip).toHaveTextContent('8% · 30d')
    expect(chip.textContent).toMatch(/trending_up/)
    // 158, 63, 78 is the muted-error tone (--error rgba).
    expect(chip.getAttribute('style')).toMatch(/158, 63, 78/)
  })

  it('flips the tone when lowerIsBetter is false', () => {
    render(<IssueDeltaChip pct={5} lowerIsBetter={false} />)
    // Positive change in a "higher is better" metric → tertiary tone.
    expect(screen.getByTestId('issue-delta-chip').getAttribute('style')).toMatch(
      /tertiary-container/,
    )
  })

  it('renders 0% as a non-positive change', () => {
    render(<IssueDeltaChip pct={0} lowerIsBetter />)
    const chip = screen.getByTestId('issue-delta-chip')
    expect(chip).toHaveTextContent('0% · 30d')
    // 0 is not "negative" → not the good direction in lowerIsBetter mode →
    // muted-error tone.
    expect(chip.getAttribute('style')).toMatch(/158, 63, 78/)
  })
})
