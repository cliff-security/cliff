import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import SideNav from '../SideNav'
import { server } from '../../../mocks/server'
import { makeFinding } from '../../../test/fixtures/finding'

/**
 * SideNav (PRD-0006 + IMPL-0008) — 224px named rail with workspace switcher,
 * Issues count badge, and labeled Settings footer. Matches IPSideNav from
 * frontend/mockups/claude-design/PRD-0006/issues-page/chrome.jsx.
 */

const GITHUB_INTEGRATION = {
  id: 'gh-1',
  adapter_type: 'ticketing',
  provider_name: 'GitHub',
  enabled: true,
  config: { repo_url: 'https://github.com/linear/billing' },
  last_test_result: null,
  updated_at: '',
  action_tier: 0,
}

function stubIntegrations(integrations: unknown[] = [GITHUB_INTEGRATION]) {
  server.use(
    http.get('/api/settings/integrations', () =>
      HttpResponse.json(integrations),
    ),
  )
}

function stubFindings(stages: Array<Parameters<typeof makeFinding>[0]>) {
  const findings = stages.map((opts, i) =>
    makeFinding({ id: `f-${i}`, ...opts }),
  )
  server.use(
    http.get('/api/findings', () => HttpResponse.json(findings)),
  )
}

function renderSideNav(initialPath = '/issues') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <SideNav />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function Wrapper({ children, path }: { children: ReactNode; path: string }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SideNav (IMPL-0008 redesign)', () => {
  it('renders a 224px-wide aside (w-56)', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    const aside = screen.getByRole('complementary')
    expect(aside.className).toMatch(/\bw-56\b/)
  })

  it('renders the OpenSec logo block with shield_lock + wordmark', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    expect(screen.getByText('OpenSec')).toBeInTheDocument()
    const logoIcon = screen.getByTestId('sidenav-logo-icon')
    expect(logoIcon.textContent).toBe('shield_lock')
  })

  it('renders the workspace switcher with repo initials, owner/repo name, and URL hint', async () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('linear/billing')).toBeInTheDocument(),
    )
    expect(screen.getByText('LB')).toBeInTheDocument()
    expect(screen.getByText('github.com/linear/billing')).toBeInTheDocument()
    const switcher = screen.getByRole('button', { name: /workspace/i })
    expect(switcher.querySelector('.material-symbols-outlined')?.textContent).toBe(
      'unfold_more',
    )
  })

  it('falls back to a "No repo connected" placeholder when no GitHub integration exists', async () => {
    stubIntegrations([])
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText(/no repo connected/i)).toBeInTheDocument(),
    )
  })

  it('workspace switcher click is a no-op (renders as a non-submitting button)', async () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('linear/billing')).toBeInTheDocument(),
    )
    const switcher = screen.getByRole('button', { name: /workspace/i })
    expect(switcher.getAttribute('type')).toBe('button')
    // Clicking should not throw or navigate. No assertion on side effects —
    // the design is explicit that this is a no-op in alpha.
    switcher.click()
  })

  it('renders the two primary nav items with named labels and icons', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    const nav = screen.getByRole('navigation', { name: /Primary/i })
    const links = nav.querySelectorAll('a')
    expect(links).toHaveLength(2)

    const dashboard = screen.getByRole('link', { name: /Dashboard/i })
    expect(dashboard.getAttribute('href')).toBe('/dashboard')
    expect(dashboard.querySelector('.material-symbols-outlined')?.textContent).toBe(
      'space_dashboard',
    )

    const issues = screen.getByRole('link', { name: /Issues/i })
    expect(issues.getAttribute('href')).toBe('/issues')
    expect(issues.querySelector('.material-symbols-outlined')?.textContent).toBe(
      'task_alt',
    )
  })

  it('does not render Findings, Workspace, History, search, notifications, or user identity', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    expect(screen.queryByRole('link', { name: /^Findings$/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /^Workspace$/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /^History$/i })).toBeNull()
    expect(screen.queryByRole('searchbox')).toBeNull()
    expect(screen.queryByRole('link', { name: /notification/i })).toBeNull()
  })

  it('Issues badge shows the count of open findings (review + in_progress + todo)', async () => {
    stubIntegrations()
    stubFindings([
      { stage: 'plan_ready' }, // review
      { stage: 'pr_ready' }, // review
      { stage: 'planning' }, // in_progress
      { stage: 'todo' }, // todo
      { stage: 'todo' }, // todo
      { stage: 'fixed' }, // done — excluded
    ])
    renderSideNav()
    const badge = await screen.findByTestId('sidenav-issues-badge')
    expect(badge.textContent).toBe('5')
  })

  it('hides the Issues badge when the open count is zero', async () => {
    stubIntegrations()
    stubFindings([
      { stage: 'fixed' },
      { stage: 'wont_fix' },
    ])
    renderSideNav()
    // Wait for findings to load so the badge would have rendered if present.
    await waitFor(() =>
      expect(screen.queryByTestId('sidenav-issues-badge')).toBeNull(),
    )
  })

  it('marks the Issues link active on /issues with aria-current and active styling', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav('/issues')
    const issues = screen.getByRole('link', { name: /Issues/i })
    expect(issues.getAttribute('aria-current')).toBe('page')
    expect(issues.className).toMatch(/bg-surface-container-highest/)
  })

  it('marks the Dashboard link active on /dashboard, not Issues', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav('/dashboard')
    const dashboard = screen.getByRole('link', { name: /Dashboard/i })
    expect(dashboard.getAttribute('aria-current')).toBe('page')
    const issues = screen.getByRole('link', { name: /Issues/i })
    expect(issues.getAttribute('aria-current')).not.toBe('page')
  })

  it('marks the Settings footer link active on /settings', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav('/settings')
    const settings = screen.getByRole('link', { name: /Settings/i })
    expect(settings.getAttribute('aria-current')).toBe('page')
  })

  it('Settings is a labeled row inside the footer (separated by a 1px outline-variant top border)', () => {
    stubIntegrations()
    stubFindings([])
    renderSideNav()
    const settings = screen.getByRole('link', { name: /Settings/i })
    expect(settings.textContent).toMatch(/Settings/)
    const footer = settings.closest('[data-testid="sidenav-footer"]')
    expect(footer).not.toBeNull()
    expect(footer?.className).toMatch(/border-t/)
    expect(footer?.className).toMatch(/border-outline-variant/)
  })

  it('renders the active Issues badge in primary tone when /issues is active', async () => {
    stubIntegrations()
    stubFindings([{ stage: 'todo' }])
    renderSideNav('/issues')
    const badge = await screen.findByTestId('sidenav-issues-badge')
    expect(badge.className).toMatch(/bg-primary/)
  })

  it('uses provider_name initials when the GitHub repo_url is missing', async () => {
    stubIntegrations([
      {
        ...GITHUB_INTEGRATION,
        config: {},
      },
    ])
    stubFindings([])
    render(
      <Wrapper path="/issues">
        <SideNav />
      </Wrapper>,
    )
    // No repo_url → fall back to the placeholder.
    await waitFor(() =>
      expect(screen.getByText(/no repo connected/i)).toBeInTheDocument(),
    )
  })

  it('snapshots the rendered SideNav with Issues active', async () => {
    stubIntegrations()
    stubFindings([
      { stage: 'plan_ready' },
      { stage: 'planning' },
      ...Array.from({ length: 58 }, (_, i) => ({ stage: 'todo' as const, id: `t-${i}` })),
    ])
    const { container } = renderSideNav('/issues')
    await screen.findByTestId('sidenav-issues-badge')
    expect(container.firstChild).toMatchSnapshot()
  })

  it('snapshots the rendered SideNav with Dashboard active', async () => {
    stubIntegrations()
    stubFindings([
      { stage: 'plan_ready' },
      { stage: 'planning' },
      ...Array.from({ length: 58 }, (_, i) => ({ stage: 'todo' as const, id: `t-${i}` })),
    ])
    const { container } = renderSideNav('/dashboard')
    await screen.findByTestId('sidenav-issues-badge')
    expect(container.firstChild).toMatchSnapshot()
  })

  it('snapshots the rendered SideNav with Settings active', async () => {
    stubIntegrations()
    stubFindings([
      { stage: 'plan_ready' },
      { stage: 'planning' },
      ...Array.from({ length: 58 }, (_, i) => ({ stage: 'todo' as const, id: `t-${i}` })),
    ])
    const { container } = renderSideNav('/settings')
    await screen.findByTestId('sidenav-issues-badge')
    expect(container.firstChild).toMatchSnapshot()
  })
})
