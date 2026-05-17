/**
 * IssueSidePanel — PRD-0006 Phase 2 / IMPL-0007 §F1+F3+F4+F5+F6.
 *
 * Tests cover:
 *  - shell renders with header + close affordance
 *  - 5 stage variants render the right section ordering
 *  - sticky footer is exactly 72px tall in every stage variant
 *  - Esc closes; outside click closes; reduced-motion path renders without throwing
 *  - Refine (R) inside Plan section opens an autofocused textarea and
 *    submitting fires the execute hook with ``user_note``
 *  - Reject (X) swaps the footer to a reason picker; submitting fires the
 *    reject hook; height stays 72px in the reject substate
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import type { Finding, IssueStage } from '../../../api/client'
import { server } from '../../../mocks/server'
import { makeFinding } from '../../../test/fixtures/finding'
import { IssueSidePanel } from '../IssueSidePanel'

function renderPanel(finding: Finding, opts: { onClose?: () => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <IssueSidePanel finding={finding} onClose={opts.onClose ?? (() => {})} />
    </QueryClientProvider>,
  )
}

function findingForStage(stage: IssueStage, overrides: Partial<Finding> = {}): Finding {
  return {
    ...makeFinding({ id: `i-${stage}`, stage, workspaceId: 'ws-1' }),
    ...overrides,
  }
}

describe('IssueSidePanel — shell (F1)', () => {
  it('renders the header with severity badge, stage chip, finding ID, and close button', () => {
    renderPanel(findingForStage('plan_ready'))
    expect(screen.getByRole('dialog', { name: /Issue details/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Close panel/i })).toBeInTheDocument()
    expect(screen.getByText('I-PLAN_READY')).toBeInTheDocument()
  })

  it('Esc key invokes onClose', () => {
    const onClose = vi.fn()
    renderPanel(findingForStage('todo'), { onClose })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicking the close button invokes onClose', () => {
    const onClose = vi.fn()
    renderPanel(findingForStage('todo'), { onClose })
    fireEvent.click(screen.getByRole('button', { name: /Close panel/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('IssueSidePanel — stage-aware section ordering (F3)', () => {
  // Activity now sits ABOVE Finding so the user lands on Cliff's output
  // first (agent run cards) with the static metadata below as supporting
  // context. The PR / Plan / Validation surfaces stay at the top.
  it.each<{ stage: IssueStage; expected: string[] }>([
    { stage: 'todo', expected: ['Activity', 'Finding'] },
    { stage: 'planning', expected: ['Plan', 'Activity', 'Finding'] },
    { stage: 'plan_ready', expected: ['Plan', 'Activity', 'Finding'] },
    { stage: 'pr_ready', expected: ['Pull request', 'Plan', 'Activity', 'Finding'] },
    {
      stage: 'fixed',
      expected: ['Validation', 'Pull request', 'Plan', 'Activity', 'Finding'],
    },
  ])('renders sections in the right order for $stage', ({ stage, expected }) => {
    renderPanel(findingForStage(stage))
    const headings = screen
      .getAllByRole('heading', { level: 3 })
      .map((h) => (h.textContent ?? '').trim())
    expect(headings).toEqual(expected)
  })
})

describe('IssueSidePanel — sticky footer (F4)', () => {
  it.each<IssueStage>(['todo', 'planning', 'plan_ready', 'pr_ready', 'fixed'])(
    'footer is exactly 72px tall for stage %s',
    (stage) => {
      renderPanel(findingForStage(stage))
      const footer = screen.getByTestId('side-panel-footer')
      expect(footer.style.height).toBe('72px')
    },
  )

  it('todo footer shows the Start primary action', () => {
    renderPanel(findingForStage('todo'))
    expect(screen.getByRole('button', { name: /^Start/i })).toBeInTheDocument()
  })

  it('plan_ready footer shows Approve, Refine, Reject', () => {
    renderPanel(findingForStage('plan_ready'))
    expect(
      screen.getByRole('button', { name: /Approve & generate fix/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Refine/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Reject/i })).toBeInTheDocument()
  })

  it('done footer shows Reopen', () => {
    renderPanel(findingForStage('fixed'))
    expect(screen.getByRole('button', { name: /Reopen/i })).toBeInTheDocument()
  })
})

describe('IssueSidePanel — Refine inline state (F5)', () => {
  it('clicking Refine reveals an autofocused textarea inside the Plan section', async () => {
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(screen.getByRole('button', { name: /^Refine/i }))
    const textarea = screen.getByPlaceholderText(/Tell the planner what to change/i)
    expect(textarea).toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).toBe(textarea))
  })

  it('Esc inside the textarea exits the refining state without submitting', () => {
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(screen.getByRole('button', { name: /^Refine/i }))
    const textarea = screen.getByPlaceholderText(/Tell the planner what to change/i)
    fireEvent.keyDown(textarea, { key: 'Escape' })
    expect(
      screen.queryByPlaceholderText(/Tell the planner what to change/i),
    ).toBeNull()
  })

  it('submitting the textarea fires the execute hook with user_note', async () => {
    let body: { user_note?: string } | null = null
    server.use(
      http.post(
        '/api/workspaces/:wsId/agents/:type/execute',
        async ({ request }) => {
          body = (await request.json()) as { user_note?: string }
          return HttpResponse.json(
            { agent_run_id: 'r-1', agent_type: 'remediation_planner', status: 'running' },
            { status: 202 },
          )
        },
      ),
    )
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(screen.getByRole('button', { name: /^Refine/i }))
    const textarea = screen.getByPlaceholderText(/Tell the planner what to change/i)
    fireEvent.change(textarea, { target: { value: 'Skip lib/normalize.ts' } })
    fireEvent.click(screen.getByRole('button', { name: /Send to agent/i }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body!.user_note).toBe('Skip lib/normalize.ts')
  })
})

// ---------------------------------------------------------------------------
// Activity error_details rendering (Q01R / B30 / IMPL-0014)
//
// When the executor reports an error in its structured_output the side panel
// must surface it inline — historically the side panel sat on "Thinking…"
// indefinitely while the agent run had a clear "Push to remote failed:
// Permission denied" message in its structured_output. The error card must
// also link to the setup-github-app guide so the user can fix the underlying
// App permission gap (the actual root cause per ADR-0037).
// ---------------------------------------------------------------------------

describe('IssueSidePanel — Activity error_details (B30)', () => {
  function withAgentRuns(workspaceId: string, runs: unknown[]) {
    server.use(
      http.get(`/api/workspaces/${workspaceId}/agent-runs`, () =>
        HttpResponse.json(runs),
      ),
    )
  }

  it('renders an inline error card with the executor error message', async () => {
    withAgentRuns('ws-1', [
      {
        id: 'run-fail',
        workspace_id: 'ws-1',
        agent_type: 'remediation_executor',
        status: 'completed',
        input_json: null,
        summary_markdown: 'Patch applied locally',
        confidence: 0.9,
        evidence_json: null,
        structured_output: {
          status: 'needs_approval',
          pr_url: null,
          error_details:
            'Push to remote failed: Permission to cliff-security/NodeGoat.git denied to galanko.',
        },
        next_action_hint: null,
        started_at: '2026-05-17T12:00:00Z',
        completed_at: '2026-05-17T12:05:00Z',
      },
    ])
    renderPanel(findingForStage('failed'))
    expect(
      await screen.findByText(/Push to remote failed/i),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /How to fix/i })
    expect(link).toHaveAttribute(
      'href',
      expect.stringContaining('setup-github-app'),
    )
  })

  it('does not render an error card when structured_output has no error_details', async () => {
    withAgentRuns('ws-1', [
      {
        id: 'run-ok',
        workspace_id: 'ws-1',
        agent_type: 'remediation_executor',
        status: 'completed',
        input_json: null,
        summary_markdown: 'Patch applied and pushed',
        confidence: 0.9,
        evidence_json: null,
        structured_output: { status: 'pr_created', pr_url: 'https://x' },
        next_action_hint: null,
        started_at: '2026-05-17T12:00:00Z',
        completed_at: '2026-05-17T12:05:00Z',
      },
    ])
    renderPanel(findingForStage('pr_ready'))
    // Wait for the activity section to render the success row, then assert
    // no error link appears.
    await screen.findByText(/Patch applied and pushed/i)
    expect(screen.queryByRole('link', { name: /How to fix/i })).toBeNull()
  })
})

describe('IssueSidePanel — Reject reason picker (F6)', () => {
  it('clicking Reject swaps the footer to a reason picker (still 72px)', () => {
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(screen.getByRole('button', { name: /^Reject/i }))
    expect(screen.getByText(/Reason/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /False positive/i }),
    ).toBeInTheDocument()
    const footer = screen.getByTestId('side-panel-footer')
    expect(footer.style.height).toBe('72px')
  })

  it('Cancel returns to the standard plan_ready footer', () => {
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(screen.getByRole('button', { name: /^Reject/i }))
    fireEvent.click(screen.getByRole('button', { name: /^Cancel$/i }))
    expect(screen.queryByText(/Reason/i)).toBeNull()
    expect(
      screen.getByRole('button', { name: /Approve & generate fix/i }),
    ).toBeInTheDocument()
  })

  it('selecting a reason and submitting fires the reject hook then closes', async () => {
    const onClose = vi.fn()
    let body: { reason?: string } | null = null
    server.use(
      http.post('/api/findings/:id/reject', async ({ request }) => {
        body = (await request.json()) as { reason?: string }
        return HttpResponse.json({
          ...makeFinding({ id: 'i-plan_ready', stage: 'false_positive' }),
          status: 'exception',
          exception_reason: 'false_positive',
          exception_note: null,
        })
      }),
    )
    renderPanel(findingForStage('plan_ready'), { onClose })
    fireEvent.click(screen.getByRole('button', { name: /^Reject/i }))
    fireEvent.click(screen.getByRole('button', { name: /False positive/i }))
    fireEvent.click(
      screen.getAllByRole('button', { name: /^Reject$/i }).slice(-1)[0],
    )
    await waitFor(() => expect(body).not.toBeNull())
    expect(body!.reason).toBe('false_positive')
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
