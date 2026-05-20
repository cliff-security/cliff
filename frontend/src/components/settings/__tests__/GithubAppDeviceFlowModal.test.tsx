/**
 * @vitest-environment jsdom
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../../mocks/server'
import { GithubAppDeviceFlowModal } from '../GithubAppDeviceFlowModal'

function wrap(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const baseConnect = {
  user_code: 'MNPQ-RSTU',
  verification_uri: 'https://github.com/login/device',
  expires_in: 900,
  interval: 5,
  install_url: 'https://github.com/apps/cliff/installations/new?state=x',
}

afterEach(() => {
  vi.useRealTimers()
})

describe('GithubAppDeviceFlowModal', () => {
  it('renders the user code, copy button, and authorization link', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: null,
          error: null,
        }),
      ),
    )

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    // Code is shown prominently — GitHub doesn't honour ?user_code=
    // pre-fill, so the user has to paste it themselves.
    expect(await screen.findByText('MNPQ-RSTU')).toBeInTheDocument()
    // Step 2 button — combined "copy + open GitHub" action. Anchor's
    // href points at the bare verification_uri (no query params); the
    // copy happens inside the click handler.
    const link = screen.getByRole('link', { name: /copy code & open github/i })
    expect(link.getAttribute('href')).toBe('https://github.com/login/device')
    expect(screen.getByLabelText(/copy code/i)).toBeInTheDocument()
  })

  it('auto-dismisses when the polled status flips to connected', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'connected',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: 42,
          github_login: 'octocat',
          error: null,
        }),
      ),
    )

    const dismissed = vi.fn()
    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={dismissed}
          onTryAgain={() => {}}
        />,
      ),
    )
    await waitFor(() => expect(dismissed).toHaveBeenCalled(), { timeout: 2000 })
  })

  it('shows the expired state and a Try again button when status=expired', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'expired',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: null,
          error: null,
        }),
      ),
    )
    const tryAgain = vi.fn()
    const user = userEvent.setup()

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={tryAgain}
        />,
      ),
    )

    expect(await screen.findByText(/code expired/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(tryAgain).toHaveBeenCalled()
  })

  it('shows the denied state when the user cancels on github.com', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'denied',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: 42,
          github_login: null,
          error: null,
        }),
      ),
    )

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    expect(
      await screen.findByText(/authorization was canceled/i),
    ).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Installation discovery (ADR-0048) — once the device is authorized
  // (github_login is set) the modal shows the install affordance or a
  // picker instead of the device-code steps.
  // -------------------------------------------------------------------------

  it('shows the install affordance when no installation is discovered', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: 'octocat',
          error: null,
        }),
      ),
      http.get(
        'http://localhost:5173/api/integrations/github/installations',
        () => HttpResponse.json({ installations: [] }),
      ),
    )

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    const link = await screen.findByTestId('github-installation-install-link')
    expect(link.getAttribute('href')).toBe(baseConnect.install_url)
    // The device-code steps are NOT shown in the awaiting-install phase.
    expect(screen.queryByText(/your one-time code/i)).not.toBeInTheDocument()
  })

  it('shows a picker when more than one installation is discovered', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: 'octocat',
          error: null,
        }),
      ),
      http.get(
        'http://localhost:5173/api/integrations/github/installations',
        () =>
          HttpResponse.json({
            installations: [
              {
                installation_id: 11,
                account_login: 'octocat',
                account_type: 'User',
              },
              {
                installation_id: 22,
                account_login: 'acme',
                account_type: 'Organization',
              },
            ],
          }),
      ),
    )

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    expect(
      await screen.findByTestId('github-installation-picker'),
    ).toBeInTheDocument()
    expect(screen.getByText('octocat')).toBeInTheDocument()
    expect(screen.getByText('acme')).toBeInTheDocument()
  })

  it('shows an error state (not the install CTA) when the lookup fails', async () => {
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: 'octocat',
          error: null,
        }),
      ),
      http.get(
        'http://localhost:5173/api/integrations/github/installations',
        () => new HttpResponse(null, { status: 503 }),
      ),
    )

    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    expect(
      await screen.findByTestId('github-installation-error'),
    ).toBeInTheDocument()
    // A failed lookup must NOT masquerade as "no installations".
    expect(
      screen.queryByTestId('github-installation-install'),
    ).not.toBeInTheDocument()
  })

  it('binds the chosen installation when a picker option is clicked', async () => {
    let selectedBody: unknown = null
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: null,
          github_login: 'octocat',
          error: null,
        }),
      ),
      http.get(
        'http://localhost:5173/api/integrations/github/installations',
        () =>
          HttpResponse.json({
            installations: [
              {
                installation_id: 11,
                account_login: 'octocat',
                account_type: 'User',
              },
              {
                installation_id: 22,
                account_login: 'acme',
                account_type: 'Organization',
              },
            ],
          }),
      ),
      http.post(
        'http://localhost:5173/api/integrations/github/installations/select',
        async ({ request }) => {
          selectedBody = await request.json()
          return HttpResponse.json({
            status: 'connected',
            user_code: 'MNPQ-RSTU',
            expires_at: null,
            installation_id: 22,
            github_login: 'octocat',
            error: null,
          })
        },
      ),
    )

    const user = userEvent.setup()
    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    const option = await screen.findByTestId('github-installation-option-22')
    await user.click(option)

    await waitFor(() =>
      expect(selectedBody).toEqual({ installation_id: 22 }),
    )
  })
})
