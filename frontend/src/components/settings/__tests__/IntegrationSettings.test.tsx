/**
 * @vitest-environment jsdom
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../../mocks/server'
import IntegrationSettings from '../IntegrationSettings'

function wrap(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // IntegrationSettings calls useNavigate() (B06 — repo-picker redirect),
  // so a router context is required.
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const githubRegistryEntry = (githubAppAvailable: boolean) => ({
  id: 'github',
  name: 'GitHub',
  adapter_type: 'finding_source',
  description: 'GitHub integration',
  icon: 'code',
  status: 'available',
  setup_guide_md: '',
  credentials_schema: [],
  config_fields: [],
  capabilities: ['collect'],
  docs_url: null,
  mcp_config: null,
  github_app_available: githubAppAvailable,
})

beforeEach(() => {
  vi.stubGlobal('open', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
})

function setupHandlers(opts: {
  githubAppAvailable: boolean
  integrations?: unknown[]
}) {
  server.use(
    http.get(
      'http://localhost:5173/api/settings/integrations/registry',
      () => HttpResponse.json([githubRegistryEntry(opts.githubAppAvailable)]),
    ),
    http.get(
      'http://localhost:5173/api/settings/integrations',
      () => HttpResponse.json(opts.integrations ?? []),
    ),
    http.get(
      'http://localhost:5173/api/settings/integrations/health',
      () => HttpResponse.json([]),
    ),
    http.get(
      'http://localhost:5173/api/integrations/github/status',
      () => HttpResponse.json(null, { status: 404 }),
    ),
    // The ConfiguredCard fetches credentials per integration row; stub
    // an empty list so a configured row can render without a 404 noise.
    http.get(
      'http://localhost:5173/api/settings/integrations/:id/credentials',
      () => HttpResponse.json([]),
    ),
  )
}

describe('IntegrationSettings — GitHub App branching', () => {
  it('shows the App Connect button on the github catalog tile when available', async () => {
    setupHandlers({ githubAppAvailable: true })
    render(wrap(<IntegrationSettings />))

    // The unique App-flow CTA on the tile.
    const connectButton = await screen.findByRole('button', { name: /connect/i })
    expect(connectButton).toBeInTheDocument()
    // The legacy "Set up" button must NOT be rendered for github.
    expect(
      screen.queryByRole('button', { name: /set up/i }),
    ).not.toBeInTheDocument()
  })

  it('falls back to the legacy "Set up" button when the App is not configured', async () => {
    setupHandlers({ githubAppAvailable: false })
    render(wrap(<IntegrationSettings />))

    expect(
      await screen.findByRole('button', { name: /set up/i }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /^connect$/i }),
    ).not.toBeInTheDocument()
  })

  it('renders the migration banner for an active PAT integration when App is available', async () => {
    setupHandlers({
      githubAppAvailable: true,
      integrations: [
        {
          id: 'pat-row',
          adapter_type: 'github',
          provider_name: 'GitHub',
          enabled: true,
          config: null,
          last_test_result: null,
          action_tier: 0,
          updated_at: new Date().toISOString(),
          // The backend stamps auth_method='pat' for PAT-onboarded
          // rows; the banner gate keys off it (no /status race).
          auth_method: 'pat',
        },
      ],
    })
    render(wrap(<IntegrationSettings />))
    await waitFor(() =>
      expect(
        screen.getByText(/switch to the new github app/i),
      ).toBeInTheDocument(),
    )
  })

  it('opens the in-place repo picker dialog when an App-flow row has no repo_url', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    setupHandlers({
      githubAppAvailable: true,
      integrations: [
        {
          id: 'app-row',
          adapter_type: 'finding_source',
          provider_name: 'GitHub',
          enabled: true,
          config: null,
          last_test_result: null,
          action_tier: 0,
          updated_at: new Date().toISOString(),
          auth_method: 'github_app',
          github_login: 'octocat',
        },
      ],
    })
    server.use(
      // The dialog lists from the vault on mount.
      http.post(
        'http://localhost:5173/api/onboarding/github/repos',
        () =>
          HttpResponse.json({
            repos: [
              {
                full_name: 'octocat/hello-world',
                html_url: 'https://github.com/octocat/hello-world',
                private: false,
                default_branch: 'main',
                can_push: true,
              },
            ],
          }),
      ),
    )
    render(wrap(<IntegrationSettings />))

    const pickButton = await screen.findByTestId('settings-pick-repo')
    // The button must be a button (not the old anchor that navigated
    // away to /onboarding/connect and dragged the user back through
    // the AI step).
    expect(pickButton.tagName).toBe('BUTTON')

    await user.click(pickButton)

    // Dialog mounts with the shared flow inside; the picker shows the
    // vault-listed repo.
    expect(await screen.findByTestId('repo-picker-dialog')).toBeInTheDocument()
    await screen.findByRole('button', { name: /octocat\/hello-world/i })
  })

  it('does not render the migration banner when App is unavailable', async () => {
    setupHandlers({
      githubAppAvailable: false,
      integrations: [
        {
          id: 'pat-row',
          adapter_type: 'finding_source',
          provider_name: 'github',
          enabled: true,
          config: null,
          last_test_result: null,
          action_tier: 0,
          updated_at: new Date().toISOString(),
        },
      ],
    })
    render(wrap(<IntegrationSettings />))
    // Wait for the configured-cards "Connected" header to render so the
    // page is fully populated before asserting the banner's absence.
    await screen.findAllByText(/connected/i)
    expect(
      screen.queryByText(/switch to the new github app/i),
    ).not.toBeInTheDocument()
  })
})
