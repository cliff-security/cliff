import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import DashboardPage from '../DashboardPage'
import { setDashboardFixture } from '../../mocks/handlers'

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('<DashboardPage />', () => {
  beforeEach(() => {
    setDashboardFixture('grade-C-with-issues')
  })

  it('renders grade C hero + completion card + vulns + posture + info line (grade-C fixture)', async () => {
    renderPage()

    await waitFor(() =>
      expect(
        screen.getByTestId('grade-ring'),
      ).toBeInTheDocument(),
    )

    expect(screen.getByTestId('grade-letter')).toHaveTextContent('C')
    expect(screen.getByTestId('CompletionProgressCard')).toBeInTheDocument()
    expect(screen.getByTestId('ScorecardInfoLine')).toBeInTheDocument()
    // At grade C the completion status card is suppressed — celebrating a
    // not-yet-complete repo would be misleading. The completion block only
    // renders at grade A with a live completion row.
    expect(
      screen.queryByTestId('CompletionStatusCard'),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Vulnerabilities')).toBeInTheDocument()
    expect(screen.getByText('Repo posture')).toBeInTheDocument()
    // PRD-0003 v0.2: count comes from ``data.criteria.filter(c => c.met)`` —
    // the labeled v0.2 list. Grade-C fixture has 6 of the 10 criteria true,
    // so the meter reads "6 criteria met · 4 remaining" and the ring shows
    // "6 of 10". (Pre-fix, the dashboard called a legacy 5-bucket counter
    // that returned 3 and then displayed it against /10 — meaningless math.)
    expect(
      screen.getByText(/6 criteria met · 4 remaining/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/6 of 10/i)).toBeInTheDocument()
  })

  it('renders grade A hero when grade-A-completion-holding fixture is active', async () => {
    setDashboardFixture('grade-A-completion-holding')
    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('grade-letter')).toHaveTextContent('A'),
    )
    expect(screen.getByText(/security completion reached/i)).toBeInTheDocument()
  })

  it('shows the AssessmentProgressList when assessment is running', async () => {
    setDashboardFixture('assessment-running')
    renderPage()

    await waitFor(() =>
      expect(
        screen.getByRole('list', { name: /assessment progress/i }),
      ).toBeInTheDocument(),
    )
    // The report card should NOT render in this state.
    expect(screen.queryByTestId('grade-ring')).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('CompletionProgressCard'),
    ).not.toBeInTheDocument()
  })

  it('uses "completion" vocabulary in dashboard copy (no stray "badge" outside Scorecard info line)', async () => {
    renderPage()
    await waitFor(() =>
      expect(screen.getByTestId('grade-ring')).toBeInTheDocument(),
    )
    // Remove the scorecard info line subtree, then assert no "badge" remains.
    const infoLine = screen.getByTestId('ScorecardInfoLine')
    infoLine.remove()
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/badge/)
  })
})
