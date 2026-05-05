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

  // ── IMPL-0009 — count mode ────────────────────────────────────────────

  describe('mode="count"', () => {
    it('renders a zero value with the remove icon and neutral tone', () => {
      render(<IssueDeltaChip mode="count" value={0} />)
      const chip = screen.getByTestId('issue-delta-chip')
      expect(chip).toHaveTextContent('— wk')
      expect(chip.textContent).toMatch(/remove/)
      expect(chip.getAttribute('style')).toMatch(/surface-container-high/)
    })

    it('renders a negative value (lowerIsBetter default) as good (tertiary)', () => {
      render(<IssueDeltaChip mode="count" value={-5} />)
      const chip = screen.getByTestId('issue-delta-chip')
      expect(chip.textContent).toMatch(/trending_down/)
      expect(chip).toHaveTextContent('−5 · wk')
      expect(chip.getAttribute('style')).toMatch(/tertiary-container/)
    })

    it('renders a positive value as bad (muted error) and prefixes with +', () => {
      render(<IssueDeltaChip mode="count" value={3} />)
      const chip = screen.getByTestId('issue-delta-chip')
      expect(chip.textContent).toMatch(/trending_up/)
      expect(chip).toHaveTextContent('+3 · wk')
      expect(chip.getAttribute('style')).toMatch(/158, 63, 78/)
    })

    it('honours lowerIsBetter=false (positive is good)', () => {
      render(<IssueDeltaChip mode="count" value={4} lowerIsBetter={false} />)
      expect(screen.getByTestId('issue-delta-chip').getAttribute('style')).toMatch(
        /tertiary-container/,
      )
    })

    it('respects custom suffix', () => {
      render(<IssueDeltaChip mode="count" value={0} suffix="mo" />)
      expect(screen.getByTestId('issue-delta-chip')).toHaveTextContent('— mo')
    })
  })
})
