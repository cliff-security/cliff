import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IssueMetricCard from '../IssueMetricCard'

describe('<IssueMetricCard />', () => {
  it('renders label, value, delta chip, and sparkline', () => {
    render(
      <IssueMetricCard
        label="Open issues"
        value="60"
        deltaPct={-8}
        lowerIsBetter
        series={[10, 20, 30, 25, 18]}
        footnote="1 open Critical · 9 High · 26 Medium · 24 Low"
      />,
    )
    expect(screen.getByText('Open issues')).toBeInTheDocument()
    expect(screen.getByTestId('issue-metric-card-value')).toHaveTextContent('60')
    expect(screen.getByTestId('issue-delta-chip')).toHaveTextContent(/8% · 30d/)
    expect(screen.getByTestId('issue-sparkline')).toBeInTheDocument()
    expect(
      screen.getByText('1 open Critical · 9 High · 26 Medium · 24 Low'),
    ).toBeInTheDocument()
  })

  it('omits the footnote when not provided', () => {
    render(
      <IssueMetricCard
        label="Time to close"
        value="11h 42m"
        deltaPct={2}
        lowerIsBetter
        series={[100, 90, 80]}
      />,
    )
    expect(screen.getByTestId('issue-metric-card-value')).toHaveTextContent('11h 42m')
    expect(screen.queryByText(/Critical/)).toBeNull()
  })

  it('renders even when the series is empty (no sparkline)', () => {
    render(
      <IssueMetricCard
        label="Open issues"
        value="0"
        deltaPct={0}
        series={[]}
      />,
    )
    expect(screen.getByTestId('issue-metric-card-value')).toHaveTextContent('0')
    expect(screen.queryByTestId('issue-sparkline')).toBeNull()
  })
})
