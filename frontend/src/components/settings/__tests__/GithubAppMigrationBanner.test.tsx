/**
 * @vitest-environment jsdom
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../../../mocks/server'
import { GithubAppMigrationBanner } from '../GithubAppMigrationBanner'

function wrap(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('GithubAppMigrationBanner', () => {
  it('renders the upgrade headline + Switch CTA', () => {
    render(wrap(<GithubAppMigrationBanner />))
    expect(screen.getByText(/switch to the new github app/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /switch/i })).toBeInTheDocument()
  })

  it('triggers the connect flow when the CTA is clicked', async () => {
    const connectCalls: number[] = []
    server.use(
      http.post(
        'http://localhost:5173/api/integrations/github/connect',
        () => {
          connectCalls.push(Date.now())
          return HttpResponse.json({
            user_code: 'AAAA-BBBB',
            verification_uri: 'https://github.com/login/device',
            expires_in: 900,
            interval: 5,
            install_url:
              'https://github.com/apps/cliff/installations/new?state=banner',
          })
        },
      ),
      http.get('http://localhost:5173/api/integrations/github/status', () =>
        HttpResponse.json({
          status: 'installation_pending',
          user_code: 'AAAA-BBBB',
          expires_at: null,
          installation_id: null,
          github_login: null,
          error: null,
        }),
      ),
    )

    // Avoid window.open opening a real popup in jsdom.
    vi.stubGlobal('open', vi.fn())

    const user = userEvent.setup()
    render(wrap(<GithubAppMigrationBanner />))
    await user.click(screen.getByRole('button', { name: /switch/i }))
    expect(connectCalls.length).toBe(1)
  })
})
