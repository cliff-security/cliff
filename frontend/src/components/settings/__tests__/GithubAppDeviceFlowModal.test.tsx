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
})
