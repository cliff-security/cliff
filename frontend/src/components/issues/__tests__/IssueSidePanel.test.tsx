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

  it('todo footer shows Run triage for an untriaged (new) finding (ADR-0051 gate)', () => {
    renderPanel(findingForStage('todo', { status: 'new' }))
    expect(
      screen.getByRole('button', { name: /run triage/i }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Start/i })).toBeNull()
  })

  it('todo footer shows Start for a confirmed-real (triaged) finding', () => {
    renderPanel(findingForStage('todo', { status: 'triaged' }))
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

describe('IssueSidePanel — Approve & generate fix (Q01R / B29)', () => {
  it('clicking Approve chains POST /plan/approve THEN POST /agents/remediation_executor/execute', async () => {
    const calls: string[] = []
    server.use(
      http.post('/api/workspaces/:wsId/plan/approve', () => {
        calls.push('approve')
        return HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        })
      }),
      http.post(
        '/api/workspaces/:wsId/agents/:type/execute',
        ({ params }) => {
          calls.push(`execute:${params.type}`)
          return HttpResponse.json(
            {
              agent_run_id: 'r-1',
              agent_type: params.type as string,
              status: 'running',
            },
            { status: 202 },
          )
        },
      ),
      // Q01R approve-plan hook invalidates the agent-runs query → MSW
      // handler must exist for the refetch to succeed (otherwise the
      // panel re-renders mid-test and unmounts the button).
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([]),
      ),
    )
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(
      screen.getByRole('button', { name: /Approve & generate fix/i }),
    )
    await waitFor(() => expect(calls).toContain('execute:remediation_executor'))
    expect(calls).toEqual(['approve', 'execute:remediation_executor'])
  })

  it('surfaces the executor 412 push-access preflight error in the footer', async () => {
    // The 412 preflight creates no agent run — without inline surfacing
    // the failure would vanish and the button would just flip back to
    // idle ("nothing happens").
    server.use(
      http.post('/api/workspaces/:wsId/plan/approve', () =>
        HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        }),
      ),
      http.post('/api/workspaces/:wsId/agents/:type/execute', () =>
        HttpResponse.json(
          {
            detail: {
              error: 'github_app_permissions',
              reason:
                'git push probe failed: credentials rejected. The stored token cannot push to this repo.',
              remediation_link: 'https://example.invalid/setup-github-app',
            },
          },
          { status: 412 },
        ),
      ),
      http.get('/api/workspaces/:wsId/agent-runs', () => HttpResponse.json([])),
    )
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(
      screen.getByRole('button', { name: /Approve & generate fix/i }),
    )
    const err = await screen.findByTestId('footer-action-error')
    expect(err).toHaveTextContent(/credentials rejected/i)
    expect(
      screen.getByRole('link', { name: /how to fix/i }),
    ).toHaveAttribute('href', 'https://example.invalid/setup-github-app')
  })

  it('shows the newest attempt error in the footer, not a stale one', async () => {
    // Attempt 1: approve OK → executor 412. Attempt 2: approve itself
    // 412s (executor never runs). The footer must show attempt 2's
    // error — per-attempt `executeAgent.reset()` keeps attempt 1's
    // stale executor error from winning the `??` precedence chain.
    server.use(
      http.post('/api/workspaces/:wsId/plan/approve', () =>
        HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        }),
      ),
      http.post('/api/workspaces/:wsId/agents/:type/execute', () =>
        HttpResponse.json(
          {
            detail: {
              error: 'github_app_permissions',
              reason: 'first failure — executor push rejected',
              remediation_link: 'https://example.invalid/fix-execute',
            },
          },
          { status: 412 },
        ),
      ),
      http.get('/api/workspaces/:wsId/agent-runs', () => HttpResponse.json([])),
      // AI provider connected — otherwise the button gates on `blockedByAI`
      // once the status query resolves, and the second click would just
      // open the provider modal instead of retrying.
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'anthropic',
          source: 'byok',
          connected_at: '2025-01-01T00:00:00Z',
          metadata: null,
          model: 'claude-haiku-4-5',
        }),
      ),
    )
    renderPanel(findingForStage('plan_ready'))
    const button = () =>
      screen.getByRole('button', { name: /Approve & generate fix/i })

    fireEvent.click(button())
    const err1 = await screen.findByTestId('footer-action-error')
    expect(err1).toHaveTextContent(/first failure/i)

    // Attempt 2: approve itself now fails — the executor never runs, so
    // attempt 1's executor error must NOT linger in the footer.
    server.use(
      http.post('/api/workspaces/:wsId/plan/approve', () =>
        HttpResponse.json(
          {
            detail: {
              error: 'github_app_permissions',
              reason: 'second failure — approve was rejected',
              remediation_link: 'https://example.invalid/fix-approve',
            },
          },
          { status: 412 },
        ),
      ),
    )
    fireEvent.click(button())
    await waitFor(() =>
      expect(screen.getByTestId('footer-action-error')).toHaveTextContent(
        /second failure/i,
      ),
    )
    expect(screen.getByTestId('footer-action-error')).not.toHaveTextContent(
      /first failure/i,
    )
  })

  it('rejects unsafe remediation_link schemes and falls back to the docs URL', async () => {
    // CodeRabbit catch: a backend bug (or attacker-controlled payload)
    // that smuggles a ``javascript:`` scheme into ``remediation_link``
    // would otherwise let a click execute script. The footer's URL
    // validator must drop the unsafe link entirely. The reason still
    // *looks like* a permissions error, so the fallback static docs
    // URL is what we expect to render.
    server.use(
      http.post('/api/workspaces/:wsId/plan/approve', () =>
        HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        }),
      ),
      http.post('/api/workspaces/:wsId/agents/:type/execute', () =>
        HttpResponse.json(
          {
            detail: {
              error: 'github_app_permissions',
              reason:
                'git push probe failed: credentials rejected by GitHub.',
              // eslint-disable-next-line no-script-url
              remediation_link: 'javascript:alert(1)',
            },
          },
          { status: 412 },
        ),
      ),
      http.get('/api/workspaces/:wsId/agent-runs', () => HttpResponse.json([])),
    )
    renderPanel(findingForStage('plan_ready'))
    fireEvent.click(
      screen.getByRole('button', { name: /Approve & generate fix/i }),
    )
    const link = await screen.findByRole('link', { name: /how to fix/i })
    const href = link.getAttribute('href') ?? ''
    expect(href).not.toMatch(/^javascript:/i)
    expect(href).toMatch(/^https:\/\//)
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

  it('How to fix link is a GitHub-hosted absolute URL (not a local /docs path)', async () => {
    // Until this fix the link pointed at ``/docs/guides/setup-github-app.md``
    // — a path the backend doesn't serve and a file extension browsers
    // don't render. The link must resolve to the GitHub-hosted markdown
    // (with anchor) so the user actually lands on the permissions section.
    withAgentRuns('ws-1', [
      {
        id: 'run-fail',
        workspace_id: 'ws-1',
        agent_type: 'remediation_executor',
        status: 'completed',
        input_json: null,
        summary_markdown: null,
        confidence: 0.9,
        evidence_json: null,
        structured_output: {
          status: 'failed',
          pr_url: null,
          error_details: 'Push denied: 403 from GitHub on git push.',
        },
        next_action_hint: null,
        started_at: '2026-05-17T12:00:00Z',
        completed_at: '2026-05-17T12:05:00Z',
      },
    ])
    renderPanel(findingForStage('failed'))
    const link = await screen.findByRole('link', { name: /How to fix/i })
    const href = link.getAttribute('href') ?? ''
    expect(href).toMatch(/^https:\/\/github\.com\//)
    expect(href).toContain('cliff-security/cliff')
    expect(href).toContain('docs/guides/setup-github-app.md')
    expect(href).toMatch(/#required-permissions$/)
  })

  it('does NOT show the How to fix link for non-permission error_details', async () => {
    // Q01R / QA — the user hit a real "Tool usage prohibited by current
    // instruction" error and the misleading "How to fix" link pointed
    // them at a GitHub-App-permissions guide unrelated to the actual
    // failure. The link must only render when error_details looks like
    // a push / permission / auth problem.
    withAgentRuns('ws-1', [
      {
        id: 'run-tool-block',
        workspace_id: 'ws-1',
        agent_type: 'remediation_executor',
        status: 'completed',
        input_json: null,
        summary_markdown: null,
        confidence: 0.9,
        evidence_json: null,
        structured_output: {
          status: 'failed',
          pr_url: null,
          error_details:
            'Tool usage prohibited by current instruction; unable to clone repository or apply fixes',
        },
        next_action_hint: null,
        started_at: '2026-05-17T12:00:00Z',
        completed_at: '2026-05-17T12:05:00Z',
      },
    ])
    renderPanel(findingForStage('failed'))
    // The error message itself must still render — we're only gating
    // the "How to fix" CTA, not the error card.
    expect(
      await screen.findByText(/Tool usage prohibited by current instruction/i),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /How to fix/i })).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Stage override: ``executor_failed`` (Q01R-W2 / B35b / IMPL-0017)
//
// When the latest remediation_executor run lands with
// ``status='completed'`` + ``structured_output.error_details``, the
// backend stage derivation can still report ``pushing`` (the executor
// created the branch locally before the git-push died). The panel must
// override that to a terminal-error stage so the header pill, top
// widget, and footer button all surface a "needs attention / retry"
// treatment instead of an indefinite spinner.
// ---------------------------------------------------------------------------

describe('IssueSidePanel — executor_failed stage override (B35b)', () => {
  function withAgentRuns(workspaceId: string, runs: unknown[]) {
    server.use(
      // AI provider status is read by every footer-button gate
      // (``blockedByAI``). The default session-handler mock returns
      // ``state='unconfigured'``, which would route every Retry click
      // into the AI-provider modal instead of the approve→execute
      // chain. The override below mirrors a configured provider so
      // these tests exercise the actual stage-derivation behavior
      // rather than the AI-gate.
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'anthropic',
          source: 'byok',
          connected_at: '2026-05-17T11:00:00Z',
          metadata: null,
          model: 'anthropic/claude-haiku-4-5',
        }),
      ),
      http.get(`/api/workspaces/${workspaceId}/agent-runs`, () =>
        HttpResponse.json(runs),
      ),
    )
  }

  const failedExecutorRun = {
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
  }

  it('renders Needs-attention pill when latest executor run has error_details', async () => {
    withAgentRuns('ws-1', [failedExecutorRun])
    // Server-derived stage is ``pushing`` — the panel must override it.
    renderPanel(findingForStage('pushing'))
    await waitFor(() =>
      expect(
        screen.getByTestId('stage-chip-executor_failed'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByText(/Needs attention/i),
    ).toBeInTheDocument()
  })

  it('does NOT show the "Pushing branch / Thinking…" widget for executor_failed', async () => {
    withAgentRuns('ws-1', [failedExecutorRun])
    renderPanel(findingForStage('pushing'))
    await waitFor(() =>
      expect(
        screen.getByTestId('stage-chip-executor_failed'),
      ).toBeInTheDocument(),
    )
    // The Plan-drafting widget renders this label for stage='pushing'.
    // After the override it must not appear.
    expect(
      screen.queryByText(/Pushing the branch to GitHub/i),
    ).toBeNull()
    expect(screen.queryByText(/Cliff is thinking/i)).toBeNull()
  })

  it('footer shows a Retry button (not Cancel run) for executor_failed', async () => {
    withAgentRuns('ws-1', [failedExecutorRun])
    renderPanel(findingForStage('pushing'))
    const retryBtn = await screen.findByRole('button', { name: /^Retry/i })
    expect(retryBtn).toBeInTheDocument()
    expect(retryBtn).not.toBeDisabled()
    expect(screen.queryByRole('button', { name: /Cancel run/i })).toBeNull()
  })

  it('Retry chains POST /plan/approve THEN POST /agents/remediation_executor/execute', async () => {
    const calls: string[] = []
    server.use(
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'anthropic',
          source: 'byok',
          connected_at: '2026-05-17T11:00:00Z',
          metadata: null,
          model: 'anthropic/claude-haiku-4-5',
        }),
      ),
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([failedExecutorRun]),
      ),
      http.post('/api/workspaces/:wsId/plan/approve', () => {
        calls.push('approve')
        return HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        })
      }),
      http.post(
        '/api/workspaces/:wsId/agents/:type/execute',
        ({ params }) => {
          calls.push(`execute:${params.type}`)
          return HttpResponse.json(
            {
              agent_run_id: 'r-1',
              agent_type: params.type as string,
              status: 'running',
            },
            { status: 202 },
          )
        },
      ),
    )
    renderPanel(findingForStage('pushing'))
    const retryBtn = await screen.findByRole('button', { name: /^Retry/i })
    fireEvent.click(retryBtn)
    await waitFor(() =>
      expect(calls).toContain('execute:remediation_executor'),
    )
    expect(calls).toEqual(['approve', 'execute:remediation_executor'])
  })

  it('Retry button is disabled while the mutation is pending (no double-fire)', async () => {
    // Block the approve call on a never-resolving promise so we can
    // observe the disabled state mid-flight.
    let releaseApprove: (() => void) = () => {}
    const approvePromise = new Promise<void>((resolve) => {
      releaseApprove = resolve
    })
    server.use(
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'anthropic',
          source: 'byok',
          connected_at: '2026-05-17T11:00:00Z',
          metadata: null,
          model: 'anthropic/claude-haiku-4-5',
        }),
      ),
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([failedExecutorRun]),
      ),
      http.post('/api/workspaces/:wsId/plan/approve', async () => {
        await approvePromise
        return HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: { approved: true, sections: [] },
          ticket: null,
          validation: null,
        })
      }),
    )
    renderPanel(findingForStage('pushing'))
    const retryBtn = await screen.findByRole('button', { name: /^Retry/i })
    fireEvent.click(retryBtn)
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Retrying…/i }),
      ).toBeDisabled(),
    )
    // Release so the test cleans up.
    releaseApprove()
  })

  it('does NOT override stage when there is no remediation_executor run', async () => {
    withAgentRuns('ws-1', [
      {
        ...failedExecutorRun,
        id: 'planner-run',
        agent_type: 'remediation_planner',
      },
    ])
    renderPanel(findingForStage('pushing'))
    // Wait for the panel to settle so the stage chip is stable.
    await waitFor(() =>
      expect(
        screen.getByTestId('stage-chip-pushing'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('stage-chip-executor_failed'),
    ).toBeNull()
  })

  it('does NOT override stage when executor run has no error_details', async () => {
    withAgentRuns('ws-1', [
      {
        ...failedExecutorRun,
        structured_output: { status: 'pr_created', pr_url: 'https://x' },
      },
    ])
    renderPanel(findingForStage('pushing'))
    await waitFor(() =>
      expect(
        screen.getByTestId('stage-chip-pushing'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('stage-chip-executor_failed'),
    ).toBeNull()
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

// ---------------------------------------------------------------------------
// Retry CTA for the generic ``failed`` stage (pre-plan failures).
//
// When a forward-pipeline prerequisite agent fails (enricher / owner_resolver
// / exposure_analyzer / evidence_collector — e.g. OpenRouter ran out of
// credits during enrichment), the side panel surfaces stage='failed' (via
// the derivation rule added alongside this test). Retry must NOT re-fire
// the executor directly (there is no plan yet — it would re-fail). It must
// re-launch the pipeline at /pipeline/run-all so suggest_next picks the
// missing section and re-runs whichever agent failed.
// ---------------------------------------------------------------------------

describe('IssueSidePanel — Retry for generic failed stage (pre-plan)', () => {
  function withConfiguredAI() {
    server.use(
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'anthropic',
          source: 'byok',
          connected_at: '2026-05-17T11:00:00Z',
          metadata: null,
          model: 'anthropic/claude-haiku-4-5',
        }),
      ),
    )
  }

  it('Retry POSTs /pipeline/run-all (NOT /agents/remediation_executor/execute)', async () => {
    withConfiguredAI()
    const calls: string[] = []
    server.use(
      http.post('/api/workspaces/:wsId/pipeline/run-all', () => {
        calls.push('run-all')
        return HttpResponse.json(
          { status: 'running', message: 'Pipeline started' },
          { status: 202 },
        )
      }),
      http.post('/api/workspaces/:wsId/agents/:type/execute', ({ params }) => {
        calls.push(`execute:${params.type}`)
        return HttpResponse.json(
          {
            agent_run_id: 'r-1',
            agent_type: params.type as string,
            status: 'running',
          },
          { status: 202 },
        )
      }),
      http.post('/api/workspaces/:wsId/plan/approve', () => {
        calls.push('approve')
        return HttpResponse.json({
          workspace_id: 'ws-1',
          summary: null,
          evidence: null,
          owner: null,
          plan: null,
          ticket: null,
          validation: null,
        })
      }),
    )

    renderPanel(findingForStage('failed'))
    const retryBtn = await screen.findByRole('button', { name: /^Retry/i })
    fireEvent.click(retryBtn)

    await waitFor(() => expect(calls).toContain('run-all'))
    expect(calls).toEqual(['run-all'])
  })
})

// ---------------------------------------------------------------------------
// Triage verdict + proof (ADR-0051 / PRD-0008 / UX-0008)
// ---------------------------------------------------------------------------

describe('IssueSidePanel — triage verdict', () => {
  function withTriage(triage: unknown, wsId = 'ws-1') {
    server.use(
      http.get(`/api/workspaces/${wsId}/sidebar`, () =>
        HttpResponse.json({
          workspace_id: wsId,
          summary: null,
          evidence: null,
          owner: null,
          plan: null,
          definition_of_done: null,
          linked_ticket: null,
          validation: null,
          similar_cases: null,
          pull_request: null,
          triage,
          updated_at: '2026-06-09T00:00:00Z',
        }),
      ),
      http.get(`/api/workspaces/${wsId}/agent-runs`, () => HttpResponse.json([])),
    )
  }

  const verdictCases: [string, string | null, string][] = [
    ['real', null, 'Real risk'],
    ['unexploitable', 'unexploitable', 'Not exploitable'],
    ['false_positive', 'false_positive', 'False positive'],
    ['needs_review', null, 'Needs your review'],
  ]

  it.each(verdictCases)(
    'renders the %s verdict banner with confidence as word + %%',
    async (verdict, close, label) => {
      withTriage({
        verdict,
        confidence: 0.88,
        recommended_close: close,
        reachability: null,
        exploitability: { exploitable: 'unknown', reason: 'depends on deployment' },
        report: null,
        checks: [],
      })
      renderPanel(findingForStage('triage_verdict'))
      const banner = await screen.findByTestId('triage-verdict-banner')
      expect(banner).toHaveTextContent(label)
      expect(screen.getByTestId('triage-confidence').textContent).toMatch(/High · 88%/)
    },
  )

  it('renders the calm "No path found" reachability state', async () => {
    withTriage({
      verdict: 'unexploitable',
      confidence: 0.9,
      recommended_close: 'unexploitable',
      reachability: { reached: false, path: [], summary: 'never called' },
      exploitability: { exploitable: 'no', reason: 'unreachable' },
      report: null,
      checks: [],
    })
    renderPanel(findingForStage('triage_verdict'))
    expect(await screen.findByTestId('reachability-no-path')).toHaveTextContent(
      /No path found/i,
    )
  })

  it('real verdict footer offers "Open workspace to remediate"', async () => {
    withTriage({
      verdict: 'real',
      confidence: 0.92,
      recommended_close: null,
      reachability: { reached: true, path: [{ label: 'upload handler' }], summary: 's' },
      exploitability: { exploitable: 'yes', reason: 'untrusted input' },
      report: null,
      checks: [{ eyebrow: 'REACHABILITY', result: 'Reachable', kind: 'fail', detail: 'd' }],
    })
    renderPanel(findingForStage('triage_verdict'))
    expect(
      await screen.findByRole('button', { name: /Open workspace to remediate/i }),
    ).toBeInTheDocument()
  })

  it('a close verdict opens the two-way close picker with radio semantics, pre-selecting the recommendation', async () => {
    withTriage({
      verdict: 'unexploitable',
      confidence: 0.86,
      recommended_close: 'unexploitable',
      reachability: { reached: false, path: [], summary: 'np' },
      exploitability: { exploitable: 'no', reason: 'unreachable' },
      report: null,
      checks: [],
    })
    renderPanel(findingForStage('triage_verdict'))
    fireEvent.click(await screen.findByRole('button', { name: /Accept & close/i }))
    expect(
      await screen.findByRole('radiogroup', { name: /Close reason/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Unexploitable/i })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    expect(screen.getByRole('radio', { name: /False positive/i })).toHaveAttribute(
      'aria-checked',
      'false',
    )
  })

  it('confirming an unexploitable close fires reject with the unexploitable reason', async () => {
    let body: { reason?: string } | null = null
    withTriage({
      verdict: 'unexploitable',
      confidence: 0.86,
      recommended_close: 'unexploitable',
      reachability: { reached: false, path: [], summary: 'np' },
      exploitability: { exploitable: 'no', reason: 'unreachable' },
      report: null,
      checks: [],
    })
    server.use(
      http.post('/api/findings/:id/reject', async ({ request }) => {
        body = (await request.json()) as { reason?: string }
        return HttpResponse.json({
          ...makeFinding({ id: 'i-triage_verdict', stage: 'unexploitable' }),
          status: 'exception',
          exception_reason: 'unexploitable',
          exception_note: null,
        })
      }),
    )
    const onClose = vi.fn()
    renderPanel(findingForStage('triage_verdict'), { onClose })
    fireEvent.click(await screen.findByRole('button', { name: /Accept & close/i }))
    fireEvent.click(
      await screen.findByRole('button', { name: /Confirm & close/i }),
    )
    await waitFor(() => expect(body).not.toBeNull())
    expect(body!.reason).toBe('unexploitable')
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('report triage renders claim-vs-code + an editable drafted reply (never auto-sent)', async () => {
    withTriage({
      verdict: 'false_positive',
      confidence: 0.8,
      recommended_close: 'false_positive',
      reachability: null,
      exploitability: null,
      report: {
        claim: 'RCE via eval',
        claim_vs_code: {
          file: 'utils.py',
          claimed: 'eval(user)',
          actual: 'ast.literal_eval(user)',
          assessment: 'Cited line uses a safe parser.',
        },
        duplicate: false,
        poc_present: false,
        ai_slop_signals: ['no concrete PoC'],
        drafted_reply: 'Thanks for the report — the cited line uses ast.literal_eval.',
      },
      checks: [],
    })
    renderPanel(findingForStage('triage_verdict'))
    expect(await screen.findByTestId('triage-claim-compare')).toHaveTextContent(
      /ast\.literal_eval/,
    )
    // AI-slop signals + PoC flag render (UX-0008 Story 5).
    const signals = screen.getByTestId('triage-report-signals')
    expect(signals).toHaveTextContent(/AI-slop signals/i)
    expect(signals).toHaveTextContent(/no concrete PoC/i)
    expect(signals).toHaveTextContent(/Proof of concept:\s*not provided/i)
    const reply = screen.getByTestId('triage-drafted-reply') as HTMLTextAreaElement
    expect(reply.value).toMatch(/Thanks for the report/)
    // Editable by the maintainer — and there is no "send" affordance: Cliff
    // never auto-sends (PRD-0008 Story 5).
    fireEvent.change(reply, { target: { value: 'My edited reply' } })
    expect(reply.value).toBe('My edited reply')
    expect(screen.queryByRole('button', { name: /^Send/i })).toBeNull()
  })

  it('a triage close (unexploitable) shows Reopen in Done', async () => {
    withTriage({
      verdict: 'unexploitable',
      confidence: 0.9,
      recommended_close: 'unexploitable',
      reachability: { reached: false, path: [], summary: 'np' },
      exploitability: { exploitable: 'no', reason: 'x' },
      report: null,
      checks: [],
    })
    renderPanel(findingForStage('unexploitable'))
    expect(
      await screen.findByRole('button', { name: /Reopen/i }),
    ).toBeInTheDocument()
  })
})

// --- Deep dive (ADR-0052 / Phase 4): exploit plan, challenge trail, provenance ---

const DEEP_DIVE_TRIAGE = {
  verdict: 'real',
  confidence: 0.9,
  recommended_close: null,
  reachability: { reached: true, path: [{ label: 'entry', detail: 'app.py:1' }], summary: null },
  exploitability: { exploitable: 'yes', reason: 'reachable with a credible path' },
  report: null,
  checks: [],
  exploit_plan: {
    hypotheses: [
      {
        id: 'h1',
        trigger_condition: 'GET /file= with a URL-like value',
        attacker_input: 'http://169.254.169.254/latest/meta-data/',
        reached_sink: 'gradio/routes.py:438',
        expected_impact: 'SSRF to the cloud metadata endpoint',
        impact_class: 'SSRF',
        confidence: 0.8,
        repro_recipe: {
          setup: ['pip install gradio'],
          docker_compose: null,
          image: 'gradio:vuln',
          ports: [7860],
          trigger: ['curl "http://target/file=http://169.254.169.254/"'],
          expected_observation: 'metadata document returned',
        },
      },
    ],
    primary_hypothesis_id: 'h1',
    no_credible_exploit: false,
  },
  challenge: {
    verdict_holds: true,
    reviewers: [
      { lens: 'reachability', verdict: 'holds', refutation: null },
      { lens: 'exploit', verdict: 'refuted', refutation: 'input is normalized upstream' },
    ],
    downgraded_verdict: null,
    confidence_adjustment: 0,
  },
  provenance: {
    steps_run: ['gather_facts', 'rule_out', 'trace_path', 'plan_exploit', 'challenge'],
    traced_sha: 'dc131b64f05062447643217819ca630e483a11df',
    model_tiers: {},
    exit_stage: 'challenge',
    escalated: true,
  },
}

function mockSidebarWithDeepDive() {
  server.use(
    http.get('/api/workspaces/:wsId/sidebar', () =>
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
        triage: DEEP_DIVE_TRIAGE,
        updated_at: '2026-06-13T00:00:00Z',
      }),
    ),
  )
}

describe('IssueSidePanel — Deep dive UI (Phase 4)', () => {
  it('renders the exploit plan with its hypothesis + repro recipe', async () => {
    mockSidebarWithDeepDive()
    renderPanel(findingForStage('triage_verdict'))
    expect(await screen.findByText(/Exploit plan/)).toBeInTheDocument()
    expect(screen.getByText('SSRF')).toBeInTheDocument()
    expect(screen.getByText(/GET \/file= with a URL-like value/)).toBeInTheDocument()
    expect(screen.getByText('gradio/routes.py:438')).toBeInTheDocument()
    expect(screen.getByText(/Reproduction recipe \(plan\)/)).toBeInTheDocument()
  })

  it('renders the challenge panel with reviewer verdicts', async () => {
    mockSidebarWithDeepDive()
    renderPanel(findingForStage('triage_verdict'))
    expect(await screen.findByText(/adversarial reviewer/)).toBeInTheDocument()
    expect(screen.getByText('Verdict held')).toBeInTheDocument()
    expect(screen.getByText('input is normalized upstream')).toBeInTheDocument()
  })

  it('renders the provenance trail with friendly stage names + traced sha', async () => {
    mockSidebarWithDeepDive()
    renderPanel(findingForStage('triage_verdict'))
    expect(await screen.findByText('How Cliff dug in')).toBeInTheDocument()
    expect(screen.getByText('Trace the path')).toBeInTheDocument()
    expect(screen.getByText('dc131b64f0')).toBeInTheDocument()
  })
})
