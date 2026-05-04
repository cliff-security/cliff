import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import IssueNeedsYouLine from '../IssueNeedsYouLine'

describe('<IssueNeedsYouLine />', () => {
  it('renders the caught-up state when all counts are zero', () => {
    render(
      <IssueNeedsYouLine plansWaiting={0} prsReady={0} criticalTodo={0} />,
    )
    const line = screen.getByTestId('issue-needs-you-line')
    expect(line).toHaveAttribute('data-state', 'caught-up')
    expect(line).toHaveTextContent(/you're caught up/i)
  })

  it('composes "three plans and two PRs are waiting on you." for 3+2', () => {
    render(
      <IssueNeedsYouLine plansWaiting={3} prsReady={2} criticalTodo={0} />,
    )
    expect(screen.getByTestId('issue-needs-you-line')).toHaveTextContent(
      'three plans and two PRs are waiting on you.',
    )
  })

  it('singularizes correctly for one plan and one PR', () => {
    render(
      <IssueNeedsYouLine plansWaiting={1} prsReady={1} criticalTodo={0} />,
    )
    expect(screen.getByTestId('issue-needs-you-line')).toHaveTextContent(
      'one plan and one PR are waiting on you.',
    )
  })

  it('renders only the plans clause when prs is zero', () => {
    render(
      <IssueNeedsYouLine plansWaiting={2} prsReady={0} criticalTodo={0} />,
    )
    expect(screen.getByTestId('issue-needs-you-line')).toHaveTextContent(
      'two plans are waiting on you.',
    )
  })

  it('falls back to a critical-todo nudge when only criticalTodo is non-zero', () => {
    render(
      <IssueNeedsYouLine plansWaiting={0} prsReady={0} criticalTodo={1} />,
    )
    expect(screen.getByTestId('issue-needs-you-line')).toHaveTextContent(
      'one critical issue is sitting in Todo.',
    )
  })

  it('fires onOpenReview when the link is clicked', () => {
    const onOpenReview = vi.fn()
    render(
      <IssueNeedsYouLine
        plansWaiting={1}
        prsReady={0}
        criticalTodo={0}
        onOpenReview={onOpenReview}
      />,
    )
    fireEvent.click(screen.getByText(/open review/i))
    expect(onOpenReview).toHaveBeenCalledTimes(1)
  })
})
