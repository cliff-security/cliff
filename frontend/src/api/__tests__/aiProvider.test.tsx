import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { useOpenRouterPolling } from '../aiProvider'
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
  return { Wrapper }
}

/**
 * B22 — when the browser regains focus mid-flight (e.g. the user has
 * just dismissed the OpenRouter consent screen and tabbed back to
 * Cliff) the polling hook needs to fire an immediate refetch so it
 * observes the now-terminal status. The default 1 s poll already gets
 * us there eventually, but tabbing back from a fully-paused tab in
 * Chrome means the next tick happens way later than 1 s.
 */
describe('useOpenRouterPolling — refetch on window focus (B22)', () => {
  it('refetches /openrouter/status when window receives focus while waiting', async () => {
    let calls = 0
    server.use(
      http.get('/api/integrations/ai/openrouter/status', () => {
        calls += 1
        return HttpResponse.json({ status: 'waiting', detail: null })
      }),
    )
    const onTerminal = vi.fn()
    const { Wrapper } = makeWrapper()
    renderHook(() => useOpenRouterPolling('sess-1', onTerminal), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(1))
    const baseline = calls

    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    await waitFor(() => expect(calls).toBeGreaterThan(baseline))
  })
})

/**
 * B22 — when the backend has forgotten the session (e.g. the
 * 5-minute listener TTL elapsed, or the singleton was restarted)
 * the /openrouter/status endpoint returns 404 but the user's key may
 * still have been persisted to AI status. Fall back to the canonical
 * /ai/status read and complete the flow if the provider connected.
 */
describe('useOpenRouterPolling — fallback to /ai/status on 404 (B22)', () => {
  it('treats a 404 on /openrouter/status as completed when /ai/status reports openrouter connected', async () => {
    server.use(
      http.get('/api/integrations/ai/openrouter/status', () =>
        HttpResponse.json({ detail: 'Unknown session_id.' }, { status: 404 }),
      ),
      http.get('/api/integrations/ai/status', () =>
        HttpResponse.json({
          state: 'connected',
          provider: 'openrouter',
          source: 'openrouter-oauth',
          connected_at: '2025-01-01T00:00:00Z',
          metadata: null,
          model: 'openrouter/anthropic/claude-sonnet-4.6',
        }),
      ),
    )
    const onTerminal = vi.fn()
    const { Wrapper } = makeWrapper()
    renderHook(() => useOpenRouterPolling('sess-2', onTerminal), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(onTerminal).toHaveBeenCalled())
    const arg = onTerminal.mock.calls.at(0)?.[0] as
      | { status?: string }
      | undefined
    expect(arg?.status).toBe('connected')
  })
})
