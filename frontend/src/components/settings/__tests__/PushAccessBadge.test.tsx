/**
 * @vitest-environment jsdom
 *
 * Tests for <PushAccessBadge> (IMPL-0018 / B35c).
 *
 * The badge fetches /api/integrations/github/diagnose on mount and
 * renders one of three states:
 *
 *   - green "Push verified" when can_push=true
 *   - red "Push blocked: {reason}" + "How to fix" link when can_push=false
 *   - nothing (rendered as null) when the endpoint returns 404
 *     (i.e. GitHub not configured — the existing "Connect GitHub"
 *     surface is what the user should see, not a scary push banner)
 *
 * These three states are the contract IssueSidePanel.tsx already pins
 * for the 412 error card; keeping the badge in lockstep means we
 * can't surface contradictory signals to the user.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '../../../mocks/server'
import { PushAccessBadge } from '../PushAccessBadge'

function wrap(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const okPayload = {
  can_push: true,
  reason: '',
  repo_url: 'https://github.com/cliff-security/NodeGoat',
  checked_at: '2026-05-17T12:00:00+00:00',
}

const blockedReason =
  "The Cliff GitHub App's installation on cliff-security/NodeGoat " +
  'declares Contents:read, not Contents:write. An org admin needs to ' +
  "approve the App's updated permissions before pushes can succeed."

const blockedPayload = {
  can_push: false,
  reason: blockedReason,
  repo_url: 'https://github.com/cliff-security/NodeGoat',
  checked_at: '2026-05-17T12:00:00+00:00',
}

describe('<PushAccessBadge>', () => {
  it('renders the green "Push verified" pill when can_push is true', async () => {
    server.use(
      http.get(
        'http://localhost:5173/api/integrations/github/diagnose',
        () => HttpResponse.json(okPayload),
      ),
    )

    render(wrap(<PushAccessBadge />))

    // We assert on the visible label, not the colour class — colour is
    // a presentation detail tested visually, but the user-visible verb
    // is the contract IssueSidePanel and the docs guide both reference.
    await waitFor(() =>
      expect(screen.getByText(/push verified/i)).toBeInTheDocument(),
    )
    // No "How to fix" link in the happy path — the link is a recovery
    // affordance and showing it next to a green pill would be confusing.
    expect(screen.queryByText(/how to fix/i)).not.toBeInTheDocument()
  })

  it('renders the red "Push blocked" pill plus the reason and a How-to-fix link when can_push is false', async () => {
    server.use(
      http.get(
        'http://localhost:5173/api/integrations/github/diagnose',
        () => HttpResponse.json(blockedPayload),
      ),
    )

    render(wrap(<PushAccessBadge />))

    // The pill label must be present so a glance at the Settings page
    // tells the user "your last/next push will fail".
    await waitFor(() =>
      expect(screen.getByText(/push blocked/i)).toBeInTheDocument(),
    )

    // The full reason from the backend must be rendered as-is — the
    // backend already wraps it in Cliff voice ("An org admin needs to
    // approve…"). Truncating or re-wording it client-side would either
    // lose the action verb or risk drifting from the executor's 412
    // error card.
    expect(
      screen.getByText(/an org admin needs to approve/i),
    ).toBeInTheDocument()

    // The "How to fix" link must deep-link to the same anchor the
    // IssueSidePanel error card uses (GITHUB_APP_PERMS_DOC_URL).
    const link = screen.getByRole('link', { name: /how to fix/i })
    expect(link).toHaveAttribute(
      'href',
      expect.stringContaining('setup-github-app'),
    )
    expect(link.getAttribute('href')).toMatch(/#required-permissions$/)
  })

  it('renders nothing when the diagnose endpoint returns 404', async () => {
    // 404 = no GitHub integration configured yet. The badge stays out
    // of the way; the existing "Connect GitHub" surface is what the
    // user should see, not a phantom red banner.
    server.use(
      http.get(
        'http://localhost:5173/api/integrations/github/diagnose',
        () =>
          HttpResponse.json(
            { detail: 'GitHub integration not configured' },
            { status: 404 },
          ),
      ),
    )

    const { container } = render(wrap(<PushAccessBadge />))

    // Wait for the query to settle then assert no badge text appeared.
    await waitFor(() => {
      // The component renders null in this state; the outer wrapper is
      // the only DOM and contains nothing.
      expect(container.querySelector('[data-testid="push-access-badge"]'))
        .toBeNull()
    })
    expect(screen.queryByText(/push verified/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/push blocked/i)).not.toBeInTheDocument()
  })
})
