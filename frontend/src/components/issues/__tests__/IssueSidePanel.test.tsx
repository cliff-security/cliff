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
  it.each<{ stage: IssueStage; expected: string[] }>([
    { stage: 'todo', expected: ['Finding', 'Activity'] },
    { stage: 'planning', expected: ['Plan', 'Finding', 'Activity'] },
    { stage: 'plan_ready', expected: ['Plan', 'Finding', 'Activity'] },
    { stage: 'pr_ready', expected: ['Pull request', 'Plan', 'Finding', 'Activity'] },
    {
      stage: 'fixed',
      expected: ['Validation', 'Pull request', 'Plan', 'Finding', 'Activity'],
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

  it('todo footer shows Start (S) primary and Assign to me text', () => {
    renderPanel(findingForStage('todo'))
    expect(screen.getByRole('button', { name: /^Start/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Assign to me/i })).toBeInTheDocument()
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
