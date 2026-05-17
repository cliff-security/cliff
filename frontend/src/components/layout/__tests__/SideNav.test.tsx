import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import SideNav from '../SideNav'
import { server } from '../../../mocks/server'
import { makeFinding } from '../../../test/fixtures/finding'

/**
 * Install a mock ``navigator.clipboard`` for the click-to-copy chip and
 * return the spy. jsdom does not ship one, and the call is async so we
 * have to wait for the writeText promise to resolve before asserting.
 */
function mockClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
    writable: true,
  })
  return writeText
}

/**
 * SideNav — the Cliff Cyberdeck navigation rail: 248px-wide aside with the
 * `cliff` wordmark header, a "current scope" workspace chip, the two
 * primary nav rows (`.cd-nav`), and a hairline-separated Settings footer.
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

/**
 * Stub ``/api/dashboard`` for the scope chip. Defaults to "no assessment
 * yet" so the chip falls through to the GitHub integration config — the
 * pre-scan UI path. Pass a ``repo_url`` to exercise the scan-first flow,
 * where the latest assessment is the authoritative current scope.
 */
function stubDashboard(repoUrl: string | null = null) {
  server.use(
    http.get('/api/dashboard', () =>
      HttpResponse.json({
        assessment: repoUrl ? { repo_url: repoUrl } : null,
      }),
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

describe('SideNav (Cliff Cyberdeck rail)', () => {
  it('renders a 248px-wide aside', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    const aside = screen.getByRole('complementary')
    expect(aside.className).toMatch(/w-\[248px\]/)
  })

  it('renders the Cliff wordmark header with the self-hosted tagline', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    expect(screen.getByText('cliff')).toBeInTheDocument()
    expect(
      screen.getByText(/self-hosted security copilot/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /cliff home/i }),
    ).toBeInTheDocument()
  })

  it('renders the workspace switcher with the :: glyph, owner/repo name, and copy affordance', async () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('linear/billing')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('sidenav-repo-initials').textContent).toBe('::')
    // The down-arrow ("expand_more") is gone — multi-scope isn't supported,
    // so the affordance is now Copy.
    expect(screen.getByTestId('sidenav-copy-icon').textContent).toBe(
      'content_copy',
    )
    const switcher = screen.getByRole('button', { name: /copy repo/i })
    expect(switcher.getAttribute('title')).toMatch(/click to copy/i)
  })

  it('shows the latest assessment repo as the current scope (scan-first flow)', async () => {
    // The scan-first CLI flow records the repo on the assessment, not as a
    // GitHub integration — the scope chip must still show it. (Bug: chip
    // read "no scope connected" while the Dashboard showed the repo.)
    stubIntegrations([])
    stubDashboard('https://github.com/cliff-security/NodeGoat')
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('cliff-security/NodeGoat')).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(/no scope connected/i),
    ).not.toBeInTheDocument()
  })

  it('prefers the latest assessment repo over the GitHub integration config', async () => {
    stubIntegrations() // linear/billing
    stubDashboard('https://github.com/cliff-security/NodeGoat')
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('cliff-security/NodeGoat')).toBeInTheDocument(),
    )
    expect(screen.queryByText('linear/billing')).not.toBeInTheDocument()
  })

  it('falls back to a "no scope connected" placeholder when no scope exists', async () => {
    stubIntegrations([])
    stubDashboard()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText(/no scope connected/i)).toBeInTheDocument(),
    )
  })

  it('copies the owner/repo to the clipboard when the scope chip is clicked', async () => {
    const writeText = mockClipboard()
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('linear/billing')).toBeInTheDocument(),
    )

    const switcher = screen.getByRole('button', { name: /copy repo/i })
    expect(switcher.getAttribute('type')).toBe('button')
    fireEvent.click(switcher)

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith('linear/billing'),
    )
  })

  it('flashes a Copied check glyph briefly after a successful copy', async () => {
    mockClipboard()
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    await waitFor(() =>
      expect(screen.getByText('linear/billing')).toBeInTheDocument(),
    )

    expect(screen.getByTestId('sidenav-copy-icon').textContent).toBe(
      'content_copy',
    )
    fireEvent.click(screen.getByRole('button', { name: /copy repo/i }))

    await waitFor(() =>
      expect(screen.getByTestId('sidenav-copy-icon').textContent).toBe('check'),
    )
    // aria-label flips to the "Copied" wording for screen-reader users.
    expect(
      screen.getByRole('button', { name: /copied .* to clipboard/i }),
    ).toBeInTheDocument()
  })

  it('renders the two primary nav items with named labels and icons', () => {
    stubIntegrations()
    stubDashboard()
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
    stubDashboard()
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
    stubDashboard()
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
    stubDashboard()
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

  it('marks the Issues link active on /issues with aria-current and the cd-nav--active class', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav('/issues')
    const issues = screen.getByRole('link', { name: /Issues/i })
    expect(issues.getAttribute('aria-current')).toBe('page')
    expect(issues.className).toMatch(/cd-nav--active/)
  })

  it('marks the Dashboard link active on /dashboard, not Issues', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav('/dashboard')
    const dashboard = screen.getByRole('link', { name: /Dashboard/i })
    expect(dashboard.getAttribute('aria-current')).toBe('page')
    const issues = screen.getByRole('link', { name: /Issues/i })
    expect(issues.getAttribute('aria-current')).not.toBe('page')
  })

  it('marks the Settings footer link active on /settings', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav('/settings')
    const settings = screen.getByRole('link', { name: /Settings/i })
    expect(settings.getAttribute('aria-current')).toBe('page')
  })

  it('Settings is a labeled row inside the footer, separated by a hairline top border', () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([])
    renderSideNav()
    const settings = screen.getByRole('link', { name: /Settings/i })
    expect(settings.textContent).toMatch(/Settings/)
    const footer = settings.closest('[data-testid="sidenav-footer"]')
    expect(footer).not.toBeNull()
    // The footer divider is a tactical hairline applied via inline style —
    // the design system forbids 1px-solid *utility* borders, not the
    // var(--cd-rule) hairline itself.
    const style = (footer as HTMLElement).getAttribute('style') ?? ''
    expect(style).toMatch(/border-top/i)
    expect(style).toMatch(/--cd-rule/)
  })

  it('renders the active Issues badge in the sage active tone when /issues is active', async () => {
    stubIntegrations()
    stubDashboard()
    stubFindings([{ stage: 'todo' }])
    renderSideNav('/issues')
    const badge = await screen.findByTestId('sidenav-issues-badge')
    expect((badge as HTMLElement).style.color).toContain('--cd-green')
  })

  it('uses the :: placeholder when the GitHub repo_url is missing and there is no assessment', async () => {
    stubIntegrations([
      {
        ...GITHUB_INTEGRATION,
        config: {},
      },
    ])
    stubDashboard()
    stubFindings([])
    render(
      <Wrapper path="/issues">
        <SideNav />
      </Wrapper>,
    )
    // No repo_url and no assessment → fall back to the placeholder.
    await waitFor(() =>
      expect(screen.getByText(/no scope connected/i)).toBeInTheDocument(),
    )
  })

  it('snapshots the rendered SideNav with Issues active', async () => {
    stubIntegrations()
    stubDashboard()
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
    stubDashboard()
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
    stubDashboard()
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
