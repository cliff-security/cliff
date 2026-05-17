/**
 * IssuesPage — Review section "Awaiting approval" sub-bucket.
 *
 * Verifies that a finding whose ``derived.stage === 'awaiting_permission'``
 * lands under a dedicated "Awaiting approval · N" hairline in the Review
 * section, ahead of the existing Errors / Plans / PRs buckets.
 *
 * The page has a deep dependency graph; we use MSW to stub the API
 * surface it actually reads and run the test against the real render.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { server } from '../mocks/server'
import IssuesPage from '@/pages/IssuesPage'
import type { Finding } from '@/api/client'

function baseFinding(overrides: Partial<Finding>): Finding {
  return {
    id: overrides.id ?? 'f1',
    source_type: 'trivy',
    source_id: overrides.id ?? 'CVE-2024-1234',
    title: overrides.title ?? 'Example CVE',
    description: null,
    plain_description: null,
    raw_severity: 'medium',
    normalized_priority: 'medium',
    asset_id: null,
    asset_label: 'api-server',
    status: 'in_progress',
    likely_owner: null,
    why_this_matters: null,
    raw_payload: null,
    type: 'vulnerability',
    grade_impact: 'minor',
    category: null,
    assessment_id: null,
    pr_url: null,
    created_at: '2026-04-24T00:00:00Z',
    updated_at: '2026-04-24T00:00:00Z',
    exception_reason: null,
    exception_note: null,
    ...overrides,
  } as Finding
}

function findings(): Finding[] {
  return [
    baseFinding({
      id: 'f-approval',
      title: 'CVE waiting on approval',
      derived: {
        section: 'review',
        stage: 'awaiting_permission',
        workspace_id: 'ws-a',
        pr_url: null,
      },
    }),
    baseFinding({
      id: 'f-error',
      title: 'CVE that errored',
      derived: {
        section: 'review',
        stage: 'failed',
        workspace_id: 'ws-b',
        pr_url: null,
      },
    }),
    baseFinding({
      id: 'f-plan',
      title: 'CVE with plan ready',
      derived: {
        section: 'review',
        stage: 'plan_ready',
        workspace_id: 'ws-c',
        pr_url: null,
      },
    }),
  ]
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return render(
    <Wrapper>
      <IssuesPage />
    </Wrapper>,
  )
}

describe('<IssuesPage /> review section — Needs you bucket', () => {
  it('renders an "Awaiting approval · N" hairline ahead of Errors and Plans waiting', async () => {
    server.use(
      http.get('/api/findings', () => HttpResponse.json(findings())),
      http.get('/api/integrations', () =>
        HttpResponse.json({ adapters: [] }),
      ),
      http.get('/api/dashboard', () =>
        HttpResponse.json({
          grade: 'C',
          score: 60,
          rationale: '',
          issues_open: 3,
          issues_resolved: 0,
          last_updated: '2026-04-24T00:00:00Z',
        }),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(
        screen.getByTestId('review-bucket-approvals'),
      ).toBeInTheDocument(),
    )

    const approvalsHeader = screen.getByTestId('review-bucket-approvals')
    expect(approvalsHeader).toHaveTextContent('Awaiting approval · 1')

    // All three sub-headers exist in the same Review section.
    const errorsHeader = screen.getByText(/Errors · 1/)
    const plansHeader = screen.getByText(/Plans waiting · 1/)

    const all = Array.from(document.querySelectorAll('.cd-hairline'))
    const approvalsIdx = all.indexOf(approvalsHeader)
    const errorsIdx = all.indexOf(errorsHeader)
    const plansIdx = all.indexOf(plansHeader)
    // Approvals must come first (most urgent) and before the others.
    expect(approvalsIdx).toBeGreaterThanOrEqual(0)
    expect(approvalsIdx).toBeLessThan(errorsIdx)
    expect(approvalsIdx).toBeLessThan(plansIdx)

    // The approval finding's title is somewhere on the page.
    expect(
      within(document.body).getByText(/CVE waiting on approval/),
    ).toBeInTheDocument()
  })
})
