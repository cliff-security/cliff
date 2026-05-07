import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import AssessmentFailedCard from '../AssessmentFailedCard'

describe('<AssessmentFailedCard />', () => {
  const baseProps = {
    message: "Couldn't clone the repository",
    failedStep: 'clone' as const,
    details:
      'git clone failed for https://github.com/x/y (exit 128): repository not found',
    onRetry: vi.fn(),
  }

  it('renders the friendly headline + per-step copy', () => {
    render(<AssessmentFailedCard {...baseProps} />)
    expect(
      screen.getByRole('heading', { name: /couldn't clone the repository/i }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('assessment-failed-step')).toHaveTextContent(
      /while cloning the repository/i,
    )
  })

  it('hides technical details behind a disclosure', () => {
    render(<AssessmentFailedCard {...baseProps} />)
    const details = screen.getByTestId('assessment-failed-details')
    // The <details> element starts collapsed.
    expect(details).not.toHaveAttribute('open')
    // The <summary> exposes the toggle affordance.
    expect(
      screen.getByText(/show technical details/i),
    ).toBeInTheDocument()
    // The raw stderr is in the DOM but inside the collapsed disclosure.
    expect(screen.getByTestId('assessment-failed-details-pre')).toHaveTextContent(
      /repository not found/i,
    )
  })

  it('omits the step copy when failed_step is unknown', () => {
    render(<AssessmentFailedCard {...baseProps} failedStep="unknown" />)
    expect(screen.queryByTestId('assessment-failed-step')).toBeNull()
  })

  it('omits the details disclosure when no details are provided', () => {
    render(<AssessmentFailedCard {...baseProps} details={null} />)
    expect(screen.queryByTestId('assessment-failed-details')).toBeNull()
  })

  it('fires onRetry when the Try again button is clicked', () => {
    const onRetry = vi.fn()
    render(<AssessmentFailedCard {...baseProps} onRetry={onRetry} />)
    fireEvent.click(screen.getByTestId('assessment-failed-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('disables the retry button while a retry is in flight', () => {
    render(<AssessmentFailedCard {...baseProps} retrying />)
    const button = screen.getByTestId('assessment-failed-retry')
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toHaveTextContent(/retrying/i)
  })
})
