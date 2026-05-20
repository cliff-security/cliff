import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { useAgentRuns } from '../hooks'
import { server } from '../../mocks/server'

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
  }
  return { client, Wrapper }
}

/**
 * B28/B29 fix — when no agent is currently running, the panel still
 * needs to refresh periodically so it can observe a freshly-completed
 * planner flipping the finding's derived stage to ``plan_ready`` (which
 * is what causes the footer's "Approve & generate fix" button to
 * appear). Stopping the poll entirely is what stalls the UI on the
 * "Thinking…" widget.
 *
 * We read the resolved ``refetchInterval`` straight off the active
 * QueryObserver so this test exercises the real hook (not a
 * re-implementation of the predicate) without depending on fake timers.
 */
describe('useAgentRuns — background polling cadence (B28/B29 fix)', () => {
  function resolveInterval(
    client: QueryClient,
    wsId: string,
  ): number | false | undefined {
    const cache = client.getQueryCache().find({
      queryKey: ['agent-runs', wsId],
    })
    if (!cache) return undefined
    const observers = cache.observers
    if (observers.length === 0) return undefined
    const opts = observers[0].options as {
      refetchInterval?:
        | number
        | false
        | ((q: unknown) => number | false | undefined)
    }
    if (typeof opts.refetchInterval === 'function') {
      // Pass the live query through so the callback sees real data.
      return opts.refetchInterval(cache)
    }
    return opts.refetchInterval
  }

  it('refetchInterval = 5000 ms when no agent is active', async () => {
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([
          {
            id: 'r-1',
            workspace_id: 'ws-1',
            agent_type: 'remediation_planner',
            status: 'completed',
            started_at: '2025-01-01T00:00:00Z',
            completed_at: '2025-01-01T00:00:10Z',
            user_note: null,
            permission_request: null,
          },
        ]),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const { result } = renderHook(() => useAgentRuns('ws-1'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(resolveInterval(client, 'ws-1')).toBe(5_000)
  })

  it('refetchInterval = 2000 ms while an agent is running', async () => {
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([
          {
            id: 'r-2',
            workspace_id: 'ws-2',
            agent_type: 'remediation_executor',
            status: 'running',
            started_at: '2025-01-01T00:00:00Z',
            completed_at: null,
            user_note: null,
            permission_request: null,
          },
        ]),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const { result } = renderHook(() => useAgentRuns('ws-2'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(resolveInterval(client, 'ws-2')).toBe(2_000)
  })

  it('refetchInterval = 5000 ms when the runs list is empty', async () => {
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json([]),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const { result } = renderHook(() => useAgentRuns('ws-3'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(resolveInterval(client, 'ws-3')).toBe(5_000)
  })
})

/**
 * B09 — when an agent run transitions into a terminal state, the side
 * panel's stage (derived from the *finding*) must refresh even if the SSE
 * stream is unavailable. ``useAgentRuns`` invalidates ['findings'] and
 * ['sidebar', wsId] off the poll so the panel doesn't stall on "Thinking…".
 */
describe('useAgentRuns — terminal-transition invalidation (B09 fix)', () => {
  function runPayload(status: string) {
    return [
      {
        id: 'r-term',
        workspace_id: 'ws-term',
        agent_type: 'exposure_analyzer',
        status,
        started_at: '2025-01-01T00:00:00Z',
        completed_at: status === 'running' ? null : '2025-01-01T00:01:00Z',
        user_note: null,
        permission_request: null,
      },
    ]
  }

  it('invalidates findings + sidebar when a run flips running → failed', async () => {
    let status = 'running'
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json(runPayload(status)),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const spy = vi.spyOn(client, 'invalidateQueries')

    const { result } = renderHook(() => useAgentRuns('ws-term'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // first load is not a transition — no invalidation yet
    spy.mockClear()

    status = 'failed'
    await result.current.refetch()

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ queryKey: ['findings'] })
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['sidebar', 'ws-term'] })
  })

  it('does not invalidate on the initial load of an already-terminal run', async () => {
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json(runPayload('failed')),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const spy = vi.spyOn(client, 'invalidateQueries')

    const { result } = renderHook(() => useAgentRuns('ws-pre'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['findings'] })
  })

  it('invalidates when a run is first observed already terminal on a later poll', async () => {
    // A fast agent can be created and fail entirely between two polls — the
    // non-terminal state is never seen, so the run appears for the first
    // time already terminal. The panel must still refresh.
    let runs: unknown[] = []
    server.use(
      http.get('/api/workspaces/:wsId/agent-runs', () =>
        HttpResponse.json(runs),
      ),
    )
    const { Wrapper, client } = makeWrapper()
    const spy = vi.spyOn(client, 'invalidateQueries')

    const { result } = renderHook(() => useAgentRuns('ws-fast'), {
      wrapper: Wrapper,
    })
    // First poll: empty — establishes the baseline.
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    spy.mockClear()

    // Next poll: a brand-new run that is already terminal.
    runs = runPayload('failed')
    await result.current.refetch()

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ queryKey: ['findings'] })
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['sidebar', 'ws-fast'] })
  })
})
