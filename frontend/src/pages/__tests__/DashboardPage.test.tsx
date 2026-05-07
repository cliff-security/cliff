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

describe('<DashboardPage /> — IMPL-0009 surfaces', () => {
  beforeEach(() => {
    setDashboardFixture('grade-B-with-history')
  })

  it('renders the four redesigned blocks (hero, open-by-severity, level-up, last-assessment)', async () => {
    renderPage()

    // Hero
    await waitFor(() =>
      expect(
        screen.getByTestId('issue-grade-hero-letter'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByTestId('issue-grade-hero-letter')).toHaveTextContent('B')

    // Open-by-severity card (left column)
    expect(screen.getByTestId('open-by-severity-card')).toBeInTheDocument()
    expect(
      screen.getByTestId('open-by-severity-row-critical'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('open-by-severity-row-high'),
    ).toBeInTheDocument()

    // Level-up panel (right column)
    expect(screen.getByTestId('level-up-panel')).toBeInTheDocument()
    expect(screen.getByTestId('gate-row-criticals_open')).toBeInTheDocument()
    expect(screen.getByTestId('gate-row-posture_remaining')).toBeInTheDocument()

    // Last-assessment panel (bottom block) — 3 scanner rows.
    expect(screen.getByTestId('last-assessment-panel')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-trivy')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-semgrep')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-posture')).toBeInTheDocument()
  })

  it('renders the grade-A hero with the "Stable" label and the completion celebration block', async () => {
    setDashboardFixture('grade-A-completion-holding')
    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('issue-grade-hero-letter')).toHaveTextContent(
        'A',
      ),
    )
    expect(screen.getByText(/^stable$/i)).toBeInTheDocument()
    // Grade A + completion_id still triggers the celebration block above
    // the new dashboard.
    expect(screen.getByTestId('completion-block')).toBeInTheDocument()
  })

  it('falls back to a friendly message when level_up is null (grade-C fixture)', async () => {
    // grade-C-with-issues has no level_up field, so the right column renders
    // the empty-state placeholder instead of the panel.
    setDashboardFixture('grade-C-with-issues')
    renderPage()
    await waitFor(() =>
      expect(screen.getByTestId('issue-grade-hero-letter')).toHaveTextContent(
        'C',
      ),
    )
    expect(screen.getByTestId('level-up-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('level-up-panel')).not.toBeInTheDocument()
  })

  it('shows the new assessment-running card when an assessment is in flight (state machine preserved)', async () => {
    setDashboardFixture('assessment-running')
    renderPage()

    await waitFor(() =>
      expect(
        screen.getByTestId('assessment-running-card'),
      ).toBeInTheDocument(),
    )
    // The new report-card surface should NOT render in this state.
    expect(screen.queryByTestId('issue-grade-hero-letter')).not.toBeInTheDocument()
    expect(screen.queryByTestId('open-by-severity-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('last-assessment-panel')).not.toBeInTheDocument()
  })

  it('renders the AssessmentFailedCard with friendly headline + step copy when status is failed (migration 015)', async () => {
    setDashboardFixture('assessment-failed')
    renderPage()

    await waitFor(() =>
      expect(
        screen.getByTestId('assessment-failed-card'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('heading', { name: /couldn't clone the repository/i }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('assessment-failed-step')).toHaveTextContent(
      /while cloning the repository/i,
    )
    // Technical details ride along, collapsed by default.
    expect(screen.getByTestId('assessment-failed-details')).not.toHaveAttribute(
      'open',
    )
    expect(
      screen.getByTestId('assessment-failed-details-pre'),
    ).toHaveTextContent(/repository not found/i)
    // Retry CTA is present (mutation is in-place; no need to click for this surface check).
    expect(screen.getByTestId('assessment-failed-retry')).toBeInTheDocument()
    // The running + report surfaces must NOT render in this state.
    expect(
      screen.queryByTestId('assessment-running-card'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('issue-grade-hero-letter'),
    ).not.toBeInTheDocument()
  })
})
