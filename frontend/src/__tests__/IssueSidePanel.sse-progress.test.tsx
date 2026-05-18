/**
 * IssueSidePanel — SSE progress-event listener (B36 / IMPL-0020).
 *
 * The agent-execution stream now multiplexes three event types:
 *   - permission_request (unchanged from PR #165)
 *   - agent_run_started (new — IMPL-0020)
 *   - agent_run_completed (new — IMPL-0020)
 *
 * Each must invalidate the ``agent-runs`` query so the activity feed
 * re-renders the instant the backend pipeline advances, removing the
 * F5 dependency surfaced in Wave 3 QA. The agent_run_started/completed
 * listeners also invalidate ``sidebar`` so the stage chip refreshes.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../mocks/server'
import { IssueSidePanel } from '@/components/issues/IssueSidePanel'
import type { Finding } from '@/api/client'

// ---------------------------------------------------------------------------
// EventSource stub — captures event listeners so we can dispatch
// synthetic SSE frames into the panel. jsdom does not ship EventSource.
// ---------------------------------------------------------------------------

type Listener = (ev: MessageEvent) => unknown

class CapturingEventSource {
  url: string
  listeners: Map<string, Listener[]> = new Map()
  constructor(url: string) {
    this.url = url
    instances.push(this)
  }
  addEventListener(type: string, listener: Listener): void {
    const arr = this.listeners.get(type) ?? []
    arr.push(listener)
    this.listeners.set(type, arr)
  }
  removeEventListener(type: string, listener: Listener): void {
    const arr = this.listeners.get(type) ?? []
    this.listeners.set(
      type,
      arr.filter((l) => l !== listener),
    )
  }
  close(): void {
    this.listeners.clear()
  }
  /** Test helper — dispatch a named SSE event to all listeners. */
  emit(type: string, data: Record<string, unknown>): void {
    const arr = this.listeners.get(type) ?? []
    for (const listener of arr) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }))
    }
  }
}

let instances: CapturingEventSource[] = []

beforeEach(() => {
  instances = []
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).EventSource = CapturingEventSource
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
      stage: 'planning',
      workspace_id: 'ws-1',
      pr_url: null,
    },
    ...overrides,
  } as Finding
}

function baseHandlers() {
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
    http.get('/api/workspaces/:id/agent-runs', () => HttpResponse.json([])),
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

function renderPanel(finding: Finding, qc: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
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

describe('<IssueSidePanel /> SSE progress events (B36)', () => {
  it('invalidates [agent-runs, workspaceId] when agent_run_completed fires', async () => {
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    renderPanel(makeFinding(), qc)

    // Wait for the effect to register the SSE.
    await waitFor(() => expect(instances.length).toBeGreaterThan(0))
    spy.mockClear()

    instances[0].emit('agent_run_completed', {
      run_id: 'run-1',
      agent_type: 'finding_enricher',
      status: 'completed',
    })

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['agent-runs', 'ws-1'],
      }),
    )
  })

  it('invalidates [agent-runs, workspaceId] when agent_run_started fires', async () => {
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    renderPanel(makeFinding(), qc)

    await waitFor(() => expect(instances.length).toBeGreaterThan(0))
    spy.mockClear()

    instances[0].emit('agent_run_started', {
      run_id: 'run-2',
      agent_type: 'owner_resolver',
      status: 'running',
    })

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['agent-runs', 'ws-1'],
      }),
    )
  })

  it('also invalidates [sidebar, workspaceId] when a progress event fires', async () => {
    // Sidebar carries the stage chip; refreshing it on a progress event
    // means the chip flips without waiting for the next poll cycle.
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    renderPanel(makeFinding(), qc)

    await waitFor(() => expect(instances.length).toBeGreaterThan(0))
    spy.mockClear()

    instances[0].emit('agent_run_completed', {
      run_id: 'run-3',
      agent_type: 'remediation_planner',
      status: 'completed',
    })

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['sidebar', 'ws-1'],
      }),
    )
  })

  it('still invalidates on permission_request (backward compat)', async () => {
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    renderPanel(makeFinding(), qc)

    await waitFor(() => expect(instances.length).toBeGreaterThan(0))
    spy.mockClear()

    instances[0].emit('permission_request', {
      id: 'p-1',
      tool: 'bash',
      patterns: ['rm', '-rf'],
      run_id: 'run-4',
    })

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['agent-runs', 'ws-1'],
      }),
    )
  })

  it('detaches listeners on unmount', async () => {
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const { unmount } = renderPanel(makeFinding(), qc)
    await waitFor(() => expect(instances.length).toBeGreaterThan(0))
    const es = instances[0]
    expect(es.listeners.get('agent_run_completed')?.length).toBeGreaterThan(0)
    unmount()
    // close() clears the listener map.
    expect(es.listeners.size).toBe(0)
  })

  it('passes a smoke render — the panel mounts even without an EventSource', async () => {
    server.use(...baseHandlers())
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    renderPanel(makeFinding(), qc)
    await waitFor(() =>
      expect(
        screen.getByRole('dialog', { name: /Issue details/i }),
      ).toBeInTheDocument(),
    )
  })
})
