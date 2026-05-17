/**
 * IssueSidePanel — permission-prompt footer.
 *
 * Covers the trust-critical bit of the agent-permission approval gate:
 *   - When the running ``remediation_executor`` carries a persisted
 *     ``permission_request`` and the finding is at stage
 *     ``awaiting_permission``, the footer renders the prompt with the
 *     command details and both Approve / Deny buttons.
 *   - Clicking Approve POSTs ``{approved: true}`` to the right URL.
 *   - Clicking Deny POSTs ``{approved: false}``.
 *   - When ``permission_request`` is null (brief poll-lag race), the
 *     footer renders a non-actionable holding state — no orphan Approve
 *     button that would dispatch ``runId`` against undefined data.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../mocks/server'
import { IssueSidePanel } from '@/components/issues/IssueSidePanel'
import type { AgentRun, Finding } from '@/api/client'

// ---------------------------------------------------------------------------
// EventSource is not available in jsdom. The side panel opens one for the
// SSE nudge — stub it with a noop so the effect runs to completion without
// hitting the real DOM API. The stub also lets us assert the URL the panel
// asked for, which is the part of the nudge that's worth covering.
// ---------------------------------------------------------------------------

const openedEventSources: string[] = []

class StubEventSource {
  url: string
  onerror: ((ev: Event) => unknown) | null = null
  onmessage: ((ev: MessageEvent) => unknown) | null = null
  onopen: ((ev: Event) => unknown) | null = null
  constructor(url: string) {
    this.url = url
    openedEventSources.push(url)
  }
  addEventListener(): void {
    /* noop */
  }
  removeEventListener(): void {
    /* noop */
  }
  close(): void {
    /* noop */
  }
}

beforeEach(() => {
  openedEventSources.length = 0
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).EventSource = StubEventSource
})

afterEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (globalThis as any).EventSource
})

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 'f1',
    source_type: 'trivy',
    source_id: 'CVE-2024-1234',
    title: 'Example CVE',
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
    created_at: '2026-04-24T00:00:00Z',
    updated_at: '2026-04-24T00:00:00Z',
    derived: {
      section: 'review',
      stage: 'awaiting_permission',
      workspace_id: 'ws-1',
      pr_url: null,
    },
    ...overrides,
  } as Finding
}

function makeRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: 'run-1',
    workspace_id: 'ws-1',
    agent_type: 'remediation_executor',
    status: 'running',
    input_json: null,
    summary_markdown: null,
    confidence: null,
    evidence_json: null,
    structured_output: null,
    next_action_hint: null,
    last_error: null,
    started_at: '2026-04-24T00:00:01Z',
    completed_at: null,
    permission_pending: true,
    permission_request: {
      id: 'perm-1',
      tool: 'bash',
      patterns: ['rm', '-rf', 'build/'],
    },
    ...overrides,
  }
}

// Minimal AI-status + sidebar handlers so the side panel's other hooks
// don't 404 and crash the render.
function baseHandlers(agentRuns: AgentRun[]) {
  return [
    http.get('/api/workspaces/:id/sidebar', () =>
      HttpResponse.json({
        workspace_id: 'ws-1',
        summary: null,
        evidence: null,
        owner: null,
        plan: null,
        definition_of_done: null,
        linked_ticket: null,
        validation: null,
        similar_cases: null,
        pull_request: null,
        updated_at: '2026-04-24T00:00:00Z',
      }),
    ),
    http.get('/api/workspaces/:id/agent-runs', () =>
      HttpResponse.json(agentRuns),
    ),
    http.get('/api/integrations/ai/status', () =>
      HttpResponse.json({
        state: 'connected',
        provider: 'anthropic',
        source: 'byok',
        connected_at: '2026-04-24T00:00:00Z',
        metadata: null,
        override_model: null,
        model: 'claude-sonnet-4-6',
      }),
    ),
  ]
}

function renderPanel(finding: Finding) {
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
      <IssueSidePanel finding={finding} onClose={vi.fn()} />
    </Wrapper>,
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('<IssueSidePanel /> permission prompt', () => {
  it('renders the prompt + tool/command and approve/deny buttons', async () => {
    server.use(...baseHandlers([makeRun()]))
    renderPanel(makeFinding())

    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )
    expect(screen.getByText('Approval needed')).toBeInTheDocument()
    expect(
      screen.getByTestId('permission-prompt-detail'),
    ).toHaveTextContent('bash · rm -rf build/')
    expect(screen.getByTestId('permission-approve')).not.toBeDisabled()
    expect(screen.getByTestId('permission-deny')).not.toBeDisabled()
  })

  it('Approve POSTs {approved:true} to the right URL', async () => {
    const calls: Array<{ url: string; body: unknown }> = []
    server.use(
      ...baseHandlers([makeRun()]),
      http.post(
        '/api/workspaces/:wsId/agent-runs/:runId/permission',
        async ({ params, request }) => {
          calls.push({
            url: `/api/workspaces/${params.wsId}/agent-runs/${params.runId}/permission`,
            body: await request.json(),
          })
          return HttpResponse.json({
            status: 'approved',
            agent_run_id: params.runId,
          })
        },
      ),
    )

    renderPanel(makeFinding())
    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId('permission-approve'))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].url).toBe(
      '/api/workspaces/ws-1/agent-runs/run-1/permission',
    )
    expect(calls[0].body).toEqual({ approved: true })
  })

  it('Deny POSTs {approved:false}', async () => {
    const calls: Array<{ body: unknown }> = []
    server.use(
      ...baseHandlers([makeRun()]),
      http.post(
        '/api/workspaces/:wsId/agent-runs/:runId/permission',
        async ({ request }) => {
          calls.push({ body: await request.json() })
          return HttpResponse.json({
            status: 'denied',
            agent_run_id: 'run-1',
          })
        },
      ),
    )

    renderPanel(makeFinding())
    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId('permission-deny'))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ approved: false })
  })

  it('surfaces a 404 from the endpoint inline so the user knows it failed', async () => {
    server.use(
      ...baseHandlers([makeRun()]),
      http.post(
        '/api/workspaces/:wsId/agent-runs/:runId/permission',
        () =>
          HttpResponse.json(
            { detail: 'No pending permission request for this agent run' },
            { status: 404 },
          ),
      ),
    )

    renderPanel(makeFinding())
    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId('permission-approve'))

    const alert = await screen.findByTestId('permission-error')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert.textContent).toMatch(/no longer pending|moved on/i)
    // Buttons must re-enable so the user can retry or switch to Deny.
    await waitFor(() =>
      expect(screen.getByTestId('permission-approve')).not.toBeDisabled(),
    )
  })

  it('surfaces a 500 from the endpoint with a retry-friendly message', async () => {
    server.use(
      ...baseHandlers([makeRun()]),
      http.post(
        '/api/workspaces/:wsId/agent-runs/:runId/permission',
        () => HttpResponse.text('Internal Server Error', { status: 500 }),
      ),
    )

    renderPanel(makeFinding())
    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId('permission-deny'))

    const alert = await screen.findByTestId('permission-error')
    expect(alert.textContent).toMatch(/try again|wasn't sent/i)
  })

  it('shows the holding state when permission_request is null (poll-lag race)', async () => {
    // derive() can route to awaiting_permission a tick before our poll
    // refreshes the AgentRun with the request details. The footer must
    // not render an orphan Approve button against undefined data.
    server.use(
      ...baseHandlers([
        makeRun({ permission_pending: true, permission_request: null }),
      ]),
    )

    renderPanel(makeFinding())
    await waitFor(() =>
      expect(
        screen.getByText('Waiting for approval details'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('permission-prompt')).not.toBeInTheDocument()
    expect(screen.queryByTestId('permission-approve')).not.toBeInTheDocument()
  })

  it('opens an SSE subscription to the workspace agent-execution stream', async () => {
    server.use(...baseHandlers([makeRun()]))
    renderPanel(makeFinding())
    await waitFor(() =>
      expect(screen.getByTestId('permission-prompt')).toBeInTheDocument(),
    )
    expect(openedEventSources).toContain(
      '/api/workspaces/ws-1/agent-execution/stream',
    )
  })
})
