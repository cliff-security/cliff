/** ADR-0037 drift banner tests.
 *
 * The Settings card has to surface the case where OpenSec's canonical
 * model and OpenCode's currently-loaded model disagree. We render the
 * card with a fixed status payload and assert the banner shows / hides
 * accordingly.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AIProviderStatus } from '../AIProviderStatus'
import type { AIStatusResponse } from '@/api/aiProvider'

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
  }
}

function mockStatus(overrides: Partial<AIStatusResponse>) {
  const payload: AIStatusResponse = {
    state: 'connected',
    provider: 'anthropic',
    source: 'byok',
    connected_at: new Date().toISOString(),
    metadata: null,
    override_model: null,
    model: 'anthropic/claude-haiku-4-5',
    live_probe: {
      ok: true,
      opencode_model: 'anthropic/claude-haiku-4-5',
    },
    ...overrides,
  }

  // Mock fetch (the shared api client wraps window.fetch).
  const originalFetch = global.fetch
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.endsWith('/api/integrations/ai/status')) {
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response('not mocked', { status: 404 })
  }) as typeof fetch

  return () => {
    global.fetch = originalFetch
  }
}

describe('AIProviderStatus drift banner', () => {
  let restoreFetch: () => void

  afterEach(() => {
    restoreFetch?.()
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not render a drift banner when canonical matches loaded', async () => {
    restoreFetch = mockStatus({})
    render(
      <AIProviderStatus
        onConnect={() => {}}
        onSwitchProvider={() => {}}
      />,
      { wrapper: wrapper() },
    )
    await screen.findByTestId('ai-provider-model-row')
    expect(
      screen.queryByTestId('ai-provider-drift-banner'),
    ).not.toBeInTheDocument()
  })

  it('renders a drift banner when OpenCode is on a different model', async () => {
    restoreFetch = mockStatus({
      model: 'anthropic/claude-haiku-4-5',
      live_probe: {
        ok: true,
        opencode_model: 'anthropic/claude-opus-4-1',
      },
    })
    render(
      <AIProviderStatus
        onConnect={() => {}}
        onSwitchProvider={() => {}}
      />,
      { wrapper: wrapper() },
    )
    const banner = await screen.findByTestId('ai-provider-drift-banner')
    expect(banner).toHaveTextContent('claude-opus-4-1')
    expect(banner).toHaveTextContent('claude-haiku-4-5')
  })

  it('does not render a drift banner when the live probe is unhealthy', async () => {
    // Singleton-down: we deliberately don't flag drift because we can't
    // tell what's actually loaded. Singleton-down has its own UX.
    restoreFetch = mockStatus({
      live_probe: { ok: false, opencode_model: null },
    })
    render(
      <AIProviderStatus
        onConnect={() => {}}
        onSwitchProvider={() => {}}
      />,
      { wrapper: wrapper() },
    )
    await screen.findByTestId('ai-provider-model-row')
    expect(
      screen.queryByTestId('ai-provider-drift-banner'),
    ).not.toBeInTheDocument()
  })
})
