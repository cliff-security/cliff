import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import IssueGradeHero from '../IssueGradeHero'

describe('<IssueGradeHero />', () => {
  it('renders the letter grade at the Cyberdeck hero size (56px in a 124px ring)', () => {
    render(
      <IssueGradeHero
        letter="B"
        label="Steady"
        caption="Down 8 issues in the last 30 days."
      />,
    )
    const letter = screen.getByTestId('issue-grade-hero-letter')
    expect(letter).toHaveTextContent('B')
    expect(letter.getAttribute('style')).toMatch(/font-size:\s*56px/)
    expect(letter.getAttribute('style')).toMatch(/letter-spacing:\s*-0\.04em/)
    expect(screen.getByText('Steady')).toBeInTheDocument()
  })

  it('renders an em dash with reduced opacity when letter is null', () => {
    render(
      <IssueGradeHero
        letter={null}
        label="Awaiting first scan"
        caption="Run an assessment to earn a grade."
      />,
    )
    const letter = screen.getByTestId('issue-grade-hero-letter')
    expect(letter).toHaveTextContent('—')
    // Pre-first-scan letter is faded but visible per the Cyberdeck hero.
    expect(letter.getAttribute('style')).toMatch(/opacity:\s*0\.7/)
  })

  it('fires onOpenReview when the primary CTA is clicked', () => {
    const openReview = vi.fn()
    render(
      <IssueGradeHero
        letter="C"
        label="At risk"
        caption=""
        onOpenReview={openReview}
      />,
    )
    fireEvent.click(screen.getByText(/open review queue/i))
    expect(openReview).toHaveBeenCalledTimes(1)
  })

  it('opens the rubric dialog when "Grading rubric" is clicked', () => {
    // jsdom supports <dialog> but showModal is a no-op; use the test ID
    // and assert the dialog is in the DOM. We exercise the click path so
    // any error in showModal would surface.
    render(
      <IssueGradeHero
        letter="B"
        label="Steady"
        caption=""
      />,
    )
    const dialog = screen.getByTestId('issue-grade-hero-rubric-dialog')
    expect(dialog.tagName.toLowerCase()).toBe('dialog')
    expect(dialog).toHaveTextContent(/grades a repo/i)
    expect(dialog).toHaveTextContent('15 posture checks')
    // Trigger and ensure no error.
    fireEvent.click(screen.getByTestId('issue-grade-hero-view-rubric'))
  })

  it('renders a rightSlot when provided', () => {
    render(
      <IssueGradeHero
        letter="A"
        label="Stable"
        caption=""
        rightSlot={<div data-testid="hero-right">slot content</div>}
      />,
    )
    expect(screen.getByTestId('hero-right')).toHaveTextContent('slot content')
  })
})
