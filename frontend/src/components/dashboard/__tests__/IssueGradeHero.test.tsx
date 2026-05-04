import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import IssueGradeHero from '../IssueGradeHero'

describe('<IssueGradeHero />', () => {
  it('renders the letter grade at hero size', () => {
    render(
      <IssueGradeHero
        letter="B"
        label="Steady"
        caption="Down 8 issues in the last 30 days."
      />,
    )
    expect(screen.getByTestId('issue-grade-hero-letter')).toHaveTextContent('B')
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
    expect(letter.getAttribute('style')).toMatch(/opacity:\s*0\.45/)
  })

  it('fires onOpenReview and onViewRubric when CTAs are clicked', () => {
    const openReview = vi.fn()
    const viewRubric = vi.fn()
    render(
      <IssueGradeHero
        letter="C"
        label="At risk"
        caption=""
        onOpenReview={openReview}
        onViewRubric={viewRubric}
      />,
    )
    fireEvent.click(screen.getByText(/open review queue/i))
    fireEvent.click(screen.getByText(/view grading rubric/i))
    expect(openReview).toHaveBeenCalledTimes(1)
    expect(viewRubric).toHaveBeenCalledTimes(1)
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
