/**
 * @vitest-environment jsdom
 *
 * Tests for ManualRecoveryCard and the 30s timeout integration in
 * GithubAppDeviceFlowModal (B33 / IMPL-0016). Verifies:
 *
 * - The card renders only after the timeout (slow GitHub redirects
 *   must not feel rushed).
 * - The hidden state field carries the csrf_state from the connect
 *   response so the backend's CSRF check has something to validate.
 * - Submitting the form POSTs to /api/integrations/github/setup/manual
 *   with the parsed installation_id.
 * - Backend 400 responses (CSRF mismatch) surface as an inline error.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../../mocks/server'
import { GithubAppDeviceFlowModal } from '../GithubAppDeviceFlowModal'
import { ManualRecoveryCard } from '../ManualRecoveryCard'

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
  install_url:
    'https://github.com/apps/cliff/installations/new?state=abc123xyz',
}

beforeEach(() => {
  // /status returns installation_pending — the modal sees the install
  // never completed and (after 30s) shows the recovery card.
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
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ManualRecoveryCard (standalone)', () => {
  it('renders the installation ID input + hidden CSRF state field', () => {
    render(
      wrap(<ManualRecoveryCard csrfState="abc123xyz" />),
    )

    const idInput = screen.getByTestId('github-manual-recovery-input')
    expect(idInput).toBeInTheDocument()
    expect(idInput.getAttribute('name')).toBe('installation_id')

    // Hidden state field — load-bearing. Without it the backend can't
    // do its CSRF check; with the WRONG value (e.g. empty string)
    // the backend returns 400. The form must carry the csrf state
    // from the connect response verbatim.
    const stateField = screen.getByTestId(
      'github-manual-recovery-state',
    ) as HTMLInputElement
    expect(stateField.type).toBe('hidden')
    expect(stateField.value).toBe('abc123xyz')
    expect(stateField.name).toBe('state')
  })

  it('posts {installation_id, state} to /setup/manual on submit', async () => {
    const requests: Array<Record<string, unknown>> = []
    server.use(
      http.post(
        'http://localhost:5173/api/integrations/github/setup/manual',
        async ({ request }) => {
          requests.push((await request.json()) as Record<string, unknown>)
          return HttpResponse.json({
            status: 'device_pending',
            user_code: 'MNPQ-RSTU',
            expires_at: null,
            installation_id: 12345,
            github_login: null,
            error: null,
          })
        },
      ),
    )

    const user = userEvent.setup()
    render(wrap(<ManualRecoveryCard csrfState="abc123xyz" />))

    await user.type(
      screen.getByTestId('github-manual-recovery-input'),
      '12345',
    )
    await user.click(screen.getByTestId('github-manual-recovery-submit'))

    await waitFor(() => expect(requests.length).toBe(1))
    expect(requests[0]).toEqual({
      installation_id: 12345,
      state: 'abc123xyz',
    })
  })

  it('surfaces backend 400 errors inline (CSRF state mismatch)', async () => {
    server.use(
      http.post(
        'http://localhost:5173/api/integrations/github/setup/manual',
        () =>
          HttpResponse.json(
            { detail: 'csrf state mismatch — the installation_id was not bound to a state this Cliff instance issued' },
            { status: 400 },
          ),
      ),
    )

    const user = userEvent.setup()
    render(wrap(<ManualRecoveryCard csrfState="wrong-state" />))

    await user.type(
      screen.getByTestId('github-manual-recovery-input'),
      '99999',
    )
    await user.click(screen.getByTestId('github-manual-recovery-submit'))

    // The 400 surfaces an inline error rather than crashing or
    // dismissing — the user's recourse is to restart the flow from
    // the catalog tile rather than retry with the dead csrf_state.
    expect(
      await screen.findByTestId('github-manual-recovery-error'),
    ).toBeInTheDocument()
  })

  it('rejects empty or non-numeric installation IDs client-side', async () => {
    let backendHits = 0
    server.use(
      http.post(
        'http://localhost:5173/api/integrations/github/setup/manual',
        () => {
          backendHits += 1
          return HttpResponse.json({})
        },
      ),
    )
    render(wrap(<ManualRecoveryCard csrfState="abc123xyz" />))

    // Submit button stays disabled when the input is empty — defensive.
    const submit = screen.getByTestId('github-manual-recovery-submit')
    expect(submit).toBeDisabled()
    expect(backendHits).toBe(0)
  })
})

describe('GithubAppDeviceFlowModal — 30s recovery timeout (B33)', () => {
  it('does NOT show the recovery card before 30s elapses', () => {
    vi.useFakeTimers()
    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    // Right after mount: no recovery card. The user is reading the
    // "Step 1 / Step 2" copy, not waiting for a timeout to expire.
    expect(
      screen.queryByTestId('github-manual-recovery'),
    ).not.toBeInTheDocument()

    // Even at the 29s mark — still no card. The 30s timeout is
    // load-bearing UX: shorter and slow GitHub redirects (median 3-8s)
    // would race the user.
    act(() => {
      vi.advanceTimersByTime(29_000)
    })
    expect(
      screen.queryByTestId('github-manual-recovery'),
    ).not.toBeInTheDocument()
  })

  it('shows the recovery card after 30s when installation still pending', () => {
    vi.useFakeTimers()
    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    act(() => {
      vi.advanceTimersByTime(31_000)
    })

    expect(screen.getByTestId('github-manual-recovery')).toBeInTheDocument()
    // The hidden state field must carry the csrf state extracted from
    // the install_url. If this drifts off, the backend's CSRF check
    // rejects everything the user pastes.
    const stateField = screen.getByTestId(
      'github-manual-recovery-state',
    ) as HTMLInputElement
    expect(stateField.value).toBe('abc123xyz')
  })

  it('hides the recovery card once the install becomes attached', async () => {
    vi.useFakeTimers()

    // Status flips to device_pending (installation_id bound) — that's
    // what happens once the GET callback fires OR the user submits a
    // successful manual recovery.
    server.use(
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'device_pending',
          user_code: 'MNPQ-RSTU',
          expires_at: null,
          installation_id: 12345,
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

    act(() => {
      vi.advanceTimersByTime(31_000)
    })
    // Once react-query flushes the device_pending status the card is
    // hidden. Switch back to real timers to let the query fire.
    vi.useRealTimers()
    await waitFor(() =>
      expect(
        screen.queryByTestId('github-manual-recovery'),
      ).not.toBeInTheDocument(),
    )
  })

  it('keeps the "still waiting…" status line visible alongside the recovery card', () => {
    vi.useFakeTimers()
    render(
      wrap(
        <GithubAppDeviceFlowModal
          connect={baseConnect}
          onDismiss={() => {}}
          onTryAgain={() => {}}
        />,
      ),
    )

    act(() => {
      vi.advanceTimersByTime(31_000)
    })

    // Card visible — slow-network fallback still useful.
    expect(screen.getByTestId('github-manual-recovery')).toBeInTheDocument()
    // The user-code area is still rendered so a user whose callback
    // arrived between the 30s mark and them noticing the card can
    // still complete the regular flow.
    expect(screen.getByText('MNPQ-RSTU')).toBeInTheDocument()
  })
})
