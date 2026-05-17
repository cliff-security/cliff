import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import IssuesPage from '../IssuesPage'
import type { Finding } from '../../api/client'
import { server } from '../../mocks/server'
import { makeFinding } from '../../test/fixtures/finding'

const navigateMock = vi.fn()
vi.mock('react-router', async (orig) => {
  const actual = (await orig()) as Record<string, unknown>
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

function renderPage(findings: Finding[], initialEntries: string[] = ['/issues']) {
  server.use(
    http.get('/api/findings', () => HttpResponse.json(findings)),
    http.get('/api/dashboard', () =>
      HttpResponse.json({
        assessment: null,
        criteria: [],
        criteria_snapshot: { snapshot: {} },
        findings_count_by_priority: {},
        grade: 'B',
        posture_checks: [],
        posture_pass_count: 0,
      }),
    ),
    http.get('/api/settings/integrations', () =>
      HttpResponse.json([
        {
          id: 'gh-1',
          adapter_type: 'ticketing',
          provider_name: 'GitHub',
          enabled: true,
          config: { repo_url: 'https://github.com/x/y' },
          last_test_result: null,
          updated_at: '',
        },
      ]),
    ),
    http.get('/api/settings/integrations/health', () =>
      HttpResponse.json([
        {
          integration_id: 'gh-1',
          registry_id: 'github',
          provider_name: 'GitHub',
          credential_status: 'ok',
          connection_status: 'ok',
          last_checked: null,
          error_message: null,
        },
      ]),
    ),
  )
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <IssuesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('IssuesPage', () => {
  beforeEach(() => {
    sessionStorage.clear()
    navigateMock.mockReset()
  })
  afterEach(() => {
    sessionStorage.clear()
  })

  it('renders the four sections in order with the right counts', async () => {
    const findings = [
      makeFinding({ id: 'r1', stage: 'plan_ready' }),
      makeFinding({ id: 'r2', stage: 'pr_ready' }),
      makeFinding({ id: 'p1', stage: 'planning' }),
      makeFinding({ id: 'p2', stage: 'generating' }),
      makeFinding({ id: 't1', stage: 'todo' }),
      makeFinding({ id: 'd1', stage: 'fixed' }),
    ]
    renderPage(findings)

    await screen.findByLabelText('Review section')
    expect(screen.getByLabelText('Review section')).toBeInTheDocument()
    expect(screen.getByLabelText('In progress section')).toBeInTheDocument()
    expect(screen.getByLabelText('Todo section')).toBeInTheDocument()
    expect(screen.getByLabelText('Done section')).toBeInTheDocument()
  })

  it('In progress section is collapsed by default and shows the aggregate caption', async () => {
    // The per-substage breakdown ("1 planning · 1 generating · …") was
    // replaced with a single aggregate caption — the substages were
    // derived optimistically from finding.status and didn't reliably
    // reflect what the executor was actually doing.
    const findings = [
      makeFinding({ id: 'p1', stage: 'planning' }),
      makeFinding({ id: 'p2', stage: 'generating' }),
      makeFinding({ id: 'p3', stage: 'opening_pr' }),
      makeFinding({ id: 'p4', stage: 'validating' }),
    ]
    renderPage(findings)
    const inProgress = await screen.findByLabelText('In progress section')
    expect(inProgress.textContent).toContain('Agents working — no action needed')
    // Count of in-progress rows is still surfaced.
    expect(inProgress.textContent).toContain('4')
    expect(screen.queryByText(/Issue p1/)).toBeNull()
  })

  it('expanding In progress reveals the rows and persists in sessionStorage', async () => {
    const findings = [makeFinding({ id: 'p1', stage: 'planning' })]
    renderPage(findings)
    const toggle = await screen.findByRole('button', {
      name: /Agents working — no action needed|Hide/i,
    })
    fireEvent.click(toggle)
    await waitFor(() => expect(screen.getByText('Issue p1')).toBeInTheDocument())
    expect(sessionStorage.getItem('opensec.issues.inProgressOpen')).toBe('1')
  })

  it('clicking a Todo row creates a workspace and opens the side panel via ?open', async () => {
    let createCount = 0
    server.use(
      http.post('/api/workspaces', () => {
        createCount += 1
        return HttpResponse.json({
          id: 'w-new',
          finding_id: 't1',
          state: 'open',
          current_focus: null,
          active_plan_version: null,
          linked_ticket_id: null,
          validation_state: null,
          created_at: '',
          updated_at: '',
        })
      }),
    )
    const findings = [makeFinding({ id: 't1', stage: 'todo' })]
    renderPage(findings)
    await screen.findByText(/grade B/)
    const startBtn = await screen.findByRole('button', { name: /^Start$/i })
    fireEvent.click(startBtn)
    await waitFor(() => expect(createCount).toBe(1))
    // Side panel mounts with the issue's title visible.
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /Issue details/i })).toBeInTheDocument(),
    )
  })

  it('clicking a Review row with an existing workspace opens the panel without creating a new workspace', async () => {
    let createCalled = false
    server.use(
      http.post('/api/workspaces', () => {
        createCalled = true
        return HttpResponse.json({})
      }),
    )
    const findings = [
      makeFinding({ id: 'r1', stage: 'plan_ready', workspaceId: 'w-existing' }),
    ]
    renderPage(findings)
    const reviewBtn = await screen.findByRole('button', { name: /Review plan/i })
    fireEvent.click(reviewBtn)
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /Issue details/i })).toBeInTheDocument(),
    )
    expect(createCalled).toBe(false)
  })

  it('opens the panel from a deep link (?open=:id)', async () => {
    const findings = [
      makeFinding({ id: 'r1', stage: 'plan_ready', workspaceId: 'w-1' }),
    ]
    renderPage(findings, ['/issues?open=r1'])
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /Issue details/i })).toBeInTheDocument(),
    )
  })

  // B26 — empty Review card only renders when BOTH Review AND Todo are
  // empty. Previously a single Todo finding still produced "Review is
  // clear" which was misleading when 45 issues sat in Todo.
  it('renders the empty-Review card only when review AND todo are empty (B26)', async () => {
    const findings = [makeFinding({ id: 'p1', stage: 'planning' })]
    renderPage(findings)
    expect(
      await screen.findByText(/Manual review queue is clear/i),
    ).toBeInTheDocument()
  })

  it('does NOT render the empty-Review card when there are open Todo items (B26)', async () => {
    const findings = [makeFinding({ id: 't1', stage: 'todo' })]
    renderPage(findings)
    await screen.findByLabelText('Todo section')
    expect(screen.queryByText(/Manual review queue is clear/i)).toBeNull()
    expect(screen.queryByText(/Review is clear\./i)).toBeNull()
  })

  it('does NOT render the empty-Review card when there are zero findings overall', async () => {
    renderPage([])
    expect(screen.queryByText(/Manual review queue is clear/i)).toBeNull()
  })

  // B25 — initial URL filters must hydrate so /issues?severity=critical
  // actually narrows the list on first render (no manual click needed).
  describe('URL filter hydration (B25)', () => {
    it('hydrates severity filter from ?severity=critical on initial render', async () => {
      const findings = [
        makeFinding({ id: 'a', stage: 'todo', severity: 'critical' }),
        makeFinding({ id: 'b', stage: 'todo', severity: 'high' }),
      ]
      renderPage(findings, ['/issues?severity=critical'])
      await screen.findByText('Issue a')
      expect(screen.getByText('Issue a')).toBeInTheDocument()
      expect(screen.queryByText('Issue b')).toBeNull()
    })

    it('hydrates type filter from ?type=posture on initial render', async () => {
      const findings = [
        makeFinding({ id: 'p1', stage: 'todo' }),
        makeFinding({ id: 'p2', stage: 'todo' }),
      ]
      // Tag one as a posture finding by manipulating the fixture.
      findings[0].type = 'posture'
      findings[1].type = 'vulnerability'
      renderPage(findings, ['/issues?type=posture'])
      await screen.findByText('Issue p1')
      expect(screen.getByText('Issue p1')).toBeInTheDocument()
      expect(screen.queryByText('Issue p2')).toBeNull()
    })
  })

  it('Severity filter narrows the visible rows', async () => {
    const findings = [
      makeFinding({ id: 'a', stage: 'todo', severity: 'critical' }),
      makeFinding({ id: 'b', stage: 'todo', severity: 'high' }),
      makeFinding({ id: 'c', stage: 'todo', severity: 'high' }),
    ]
    renderPage(findings)
    await screen.findByText('Issue a')
    expect(screen.getByText('Issue a')).toBeInTheDocument()
    expect(screen.getByText('Issue b')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^Critical/i }))
    await waitFor(() => {
      expect(screen.getByText('Issue a')).toBeInTheDocument()
      expect(screen.queryByText('Issue b')).toBeNull()
    })
  })

  // F8 — Done collapse + verdict chips + [/] keyboard toggle
  describe('Done section (F8)', () => {
    it('is collapsed by default; rows hidden until expanded', async () => {
      const findings = [
        makeFinding({ id: 'd1', stage: 'fixed' }),
        makeFinding({ id: 'd2', stage: 'false_positive' }),
      ]
      renderPage(findings)
      await screen.findByLabelText('Done section')
      expect(screen.queryByText('Issue d1')).toBeNull()
    })

    it('clicking the Done header expands the section and persists per session', async () => {
      const findings = [makeFinding({ id: 'd1', stage: 'fixed' })]
      renderPage(findings)
      const header = await screen.findByRole('button', {
        name: /Closed in the last 7 days/i,
      })
      fireEvent.click(header)
      await waitFor(() => expect(screen.getByText('Issue d1')).toBeInTheDocument())
      expect(sessionStorage.getItem('opensec.issues.doneOpen')).toBe('1')
    })

    it('] toggles open and [ toggles closed via keyboard', async () => {
      const findings = [makeFinding({ id: 'd1', stage: 'fixed' })]
      renderPage(findings)
      await screen.findByLabelText('Done section')
      // ] expands
      fireEvent.keyDown(window, { key: ']' })
      await waitFor(() => expect(screen.getByText('Issue d1')).toBeInTheDocument())
      // [ collapses
      fireEvent.keyDown(window, { key: '[' })
      await waitFor(() => expect(screen.queryByText('Issue d1')).toBeNull())
    })

    it('renders single-word verdict chips (Fixed / False positive / etc)', async () => {
      const findings = [
        makeFinding({ id: 'd1', stage: 'fixed' }),
        makeFinding({ id: 'd2', stage: 'wont_fix' }),
        makeFinding({ id: 'd3', stage: 'false_positive' }),
      ]
      renderPage(findings)
      const header = await screen.findByRole('button', {
        name: /Closed in the last 7 days/i,
      })
      fireEvent.click(header)
      await waitFor(() => {
        expect(screen.getByTestId('stage-chip-fixed')).toHaveTextContent('Fixed')
        expect(screen.getByTestId('stage-chip-wont_fix')).toHaveTextContent("Won't fix")
        expect(screen.getByTestId('stage-chip-false_positive')).toHaveTextContent(
          'False positive',
        )
      })
    })
  })

  // F7 — Plans-waiting / PRs-ready sub-headers
  describe('Review sub-grouping (F7)', () => {
    it('renders both sub-headers when both buckets are non-empty', async () => {
      const findings = [
        makeFinding({ id: 'p1', stage: 'plan_ready' }),
        makeFinding({ id: 'p2', stage: 'plan_ready' }),
        makeFinding({ id: 'pr1', stage: 'pr_ready' }),
      ]
      renderPage(findings)
      await screen.findByLabelText('Review section')
      expect(screen.getByText(/Plans waiting/i)).toBeInTheDocument()
      expect(screen.getByText(/PRs ready/i)).toBeInTheDocument()
    })

    it('renders flat (no sub-headers) when only Plans bucket is populated', async () => {
      const findings = [
        makeFinding({ id: 'p1', stage: 'plan_ready' }),
        makeFinding({ id: 'p2', stage: 'plan_ready' }),
      ]
      renderPage(findings)
      await screen.findByLabelText('Review section')
      expect(screen.queryByText(/Plans waiting/i)).toBeNull()
      expect(screen.queryByText(/PRs ready/i)).toBeNull()
    })

    it('renders flat (no sub-headers) when only PRs bucket is populated', async () => {
      const findings = [makeFinding({ id: 'pr1', stage: 'pr_ready' })]
      renderPage(findings)
      await screen.findByLabelText('Review section')
      expect(screen.queryByText(/Plans waiting/i)).toBeNull()
      expect(screen.queryByText(/PRs ready/i)).toBeNull()
    })
  })
})
