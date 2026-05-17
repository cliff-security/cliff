/**
 * ModelPicker tests (architect test-coverage gap H4).
 *
 * ModelPicker is 374 lines and was 0% covered before — it's the only
 * UI for switching models post-onboarding. These tests cover the four
 * states the picker can be in (loading, error, cloud-catalog,
 * ollama-empty) plus the custom-id submit path.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../../mocks/server'
import { ModelPicker } from '../ModelPicker'

afterEach(() => {
  server.resetHandlers()
})

function renderPicker(
  props: Partial<React.ComponentProps<typeof ModelPicker>> = {},
) {
  const onClose = props.onClose ?? vi.fn()
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  const utils = render(
    <QueryClientProvider client={client}>
      <ModelPicker
        provider={props.provider ?? 'anthropic'}
        currentModel={props.currentModel ?? null}
        onClose={onClose}
        triggerId={props.triggerId}
      />
    </QueryClientProvider>,
  )
  return { ...utils, onClose, client }
}

describe('ModelPicker', () => {
  it('renders the cloud catalog and marks the current model Active', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.json({
          provider: 'anthropic',
          default_model: 'anthropic/claude-haiku-4-5',
          models: [
            {
              id: 'anthropic/claude-haiku-4-5',
              label: 'Claude Haiku 4.5',
              description: 'Default — cheapest current-generation Claude.',
            },
            {
              id: 'anthropic/claude-sonnet-4-6',
              label: 'Claude Sonnet 4.6',
              description: 'Best security reasoning. ~5× cost of Haiku.',
            },
          ],
          source: 'catalog',
        }),
      ),
    )

    renderPicker({
      provider: 'anthropic',
      currentModel: 'anthropic/claude-sonnet-4-6',
    })

    await waitFor(() =>
      expect(
        screen.getByText('anthropic/claude-haiku-4-5'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('anthropic/claude-sonnet-4-6')).toBeInTheDocument()
    // Sonnet is the current model → "Active" chip.
    expect(screen.getByText('Active')).toBeInTheDocument()
    // Haiku is the catalog default but NOT current → "Default" chip.
    expect(screen.getByText('Default')).toBeInTheDocument()
  })

  it('surfaces a retryable error when the models endpoint fails', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.error(),
      ),
    )
    renderPicker({ provider: 'anthropic' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the model list')
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows the "pull a model first" hint when Ollama returns no tags', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.json({
          provider: 'ollama',
          default_model: null,
          models: [],
          source: 'live',
        }),
      ),
    )
    renderPicker({ provider: 'ollama' })
    await waitFor(() =>
      expect(
        screen.getByText(/No Ollama models found/i),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/ollama pull llama3.2/)).toBeInTheDocument()
    // "live from ollama" tag in the header
    expect(screen.getByText(/live from ollama/i)).toBeInTheDocument()
  })

  it('submits a custom model id via PUT /model and closes on success', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.json({
          provider: 'openrouter',
          default_model: 'openrouter/anthropic/claude-haiku-4.5',
          models: [],
          source: 'catalog',
        }),
      ),
      http.put('/api/integrations/ai/model', async ({ request }) => {
        const body = (await request.json()) as { model: string }
        // Echo the chosen model back as the new status; ModelPicker only
        // needs the call to succeed to close.
        return HttpResponse.json({
          state: 'connected',
          provider: 'openrouter',
          source: 'byok',
          connected_at: '2026-05-17T00:00:00Z',
          metadata: null,
          model: body.model,
        })
      }),
    )

    const onClose = vi.fn()
    renderPicker({ provider: 'openrouter', onClose })

    const input = await screen.findByLabelText(/Or paste a custom model id/i)
    await userEvent.type(input, 'openrouter/x/some-private-model')
    await userEvent.click(screen.getByRole('button', { name: /^Use$/ }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('surfaces a structured API error when the PUT fails', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.json({
          provider: 'anthropic',
          default_model: 'anthropic/claude-haiku-4-5',
          models: [
            {
              id: 'anthropic/claude-haiku-4-5',
              label: 'Claude Haiku 4.5',
              description: 'd',
            },
          ],
          source: 'catalog',
        }),
      ),
      http.put('/api/integrations/ai/model', () =>
        HttpResponse.json(
          { detail: 'Model id prefix must match the active provider.' },
          { status: 400 },
        ),
      ),
    )

    const onClose = vi.fn()
    renderPicker({ provider: 'anthropic', onClose })

    const haiku = await screen.findByText('anthropic/claude-haiku-4-5')
    await userEvent.click(haiku.closest('button') as HTMLButtonElement)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/prefix must match the active provider/i)
    // Picker must NOT close on error so the user can correct.
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Escape closes the picker', async () => {
    server.use(
      http.get('/api/integrations/ai/models', () =>
        HttpResponse.json({
          provider: 'anthropic',
          default_model: null,
          models: [],
          source: 'catalog',
        }),
      ),
    )
    const onClose = vi.fn()
    renderPicker({ provider: 'anthropic', onClose })
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
