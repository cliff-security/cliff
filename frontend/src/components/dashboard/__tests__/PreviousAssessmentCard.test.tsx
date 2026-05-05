import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PreviousAssessmentCard from '../PreviousAssessmentCard'

describe('<PreviousAssessmentCard />', () => {
  it('renders the eyebrow + grade + open count + commit', () => {
    render(
      <PreviousAssessmentCard
        info={{
          assessment_id: 'asmt_prev_1',
          grade: 'C',
          open_count: 60,
          commit_sha: 'a3f81c2',
          finished_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
          report_href: '/dashboard?assessment_id=asmt_prev_1',
        }}
      />,
    )
    const card = screen.getByTestId('previous-assessment-card')
    expect(card).toHaveTextContent('Previous assessment')
    expect(card).toHaveTextContent('Grade C')
    expect(card).toHaveTextContent('60 open findings')
    expect(card).toHaveTextContent('a3f81c2')
    expect(card).toHaveTextContent('12 minutes ago')
  })

  it('clicking "View last report" fires onViewLastReport', () => {
    const onViewLastReport = vi.fn()
    render(
      <PreviousAssessmentCard
        info={{
          assessment_id: 'asmt_prev_2',
          grade: 'B',
          open_count: 5,
          commit_sha: 'beefc0de',
          report_href: '/dashboard?assessment_id=asmt_prev_2',
        }}
        onViewLastReport={onViewLastReport}
      />,
    )
    fireEvent.click(screen.getByText(/View last report/i))
    expect(onViewLastReport).toHaveBeenCalledTimes(1)
  })
})
