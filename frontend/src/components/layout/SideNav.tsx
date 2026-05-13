import { NavLink } from 'react-router'
import { useIntegrations, useOpenIssuesCount } from '@/api/hooks'

/**
 * Primary navigation rail — Cliff Cyberdeck dress.
 *
 * 232px named rail in `--cd-bg-1` (navy step up from the body) with a
 * hairline right edge. The header carries the operator "node id" label
 * + the lowercase `cliff` wordmark with the sage pulse dot. The repo
 * chip below shows the current scope in cyan mono. Primary nav rows use
 * the mono uppercase `.cd-nav` style with a 2px left border that
 * energises to sage on the active row. The footer Settings row sits
 * above a hairline.
 *
 * Per the handoff: never `1px solid` for atmospheric borders — the
 * three borders here (aside right edge, header underline, footer
 * divider) are tactical hairlines using `var(--cd-rule)`.
 */

type NavItem = {
  to: string
  label: string
  icon: string
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { to: '/dashboard', label: 'Dashboard', icon: 'space_dashboard' },
  { to: '/issues', label: 'Issues', icon: 'task_alt' },
]

const focusRing =
  'focus-visible:outline-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-[var(--cd-green)]'

function NavIcon({ name }: { name: string }) {
  return (
    <span
      className="material-symbols-outlined"
      aria-hidden
      style={{
        fontSize: 15,
        fontVariationSettings: `'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24`,
      }}
    >
      {name}
    </span>
  )
}

/** lowercase "cliff" wordmark with the sage pulse dot. */
function CliffWordmark() {
  return (
    <span
      className="inline-flex items-baseline gap-[1px]"
      style={{ lineHeight: 1 }}
    >
      <span
        className="font-display font-extrabold"
        style={{
          fontSize: 26,
          letterSpacing: '-0.045em',
          color: 'var(--cd-green)',
          textShadow: '0 0 14px var(--cd-green-glow)',
        }}
      >
        cliff
      </span>
      <span
        className="cd-pulse ml-[3px]"
        style={{
          width: 5,
          height: 5,
          background: 'var(--cd-green)',
          boxShadow: '0 0 8px var(--cd-green)',
        }}
        aria-hidden
      />
    </span>
  )
}

/**
 * Derive a 2-character avatar from a GitHub-style repo URL.
 * "github.com/linear/billing" → "LB". Falls back to the first two chars of
 * the provider name if the URL is unparseable.
 */
function repoInitials(repoUrl: string | undefined, providerName: string): string {
  if (repoUrl) {
    try {
      const stripped = repoUrl.replace(/^https?:\/\//, '').replace(/\.git$/, '')
      const parts = stripped.split('/').filter(Boolean)
      if (parts.length >= 3) {
        const owner = parts[1]
        const repo = parts[2]
        return `${owner[0] ?? ''}${repo[0] ?? ''}`.toUpperCase()
      }
    } catch {
      // fall through
    }
  }
  return providerName.slice(0, 2).toUpperCase()
}

function repoDisplayName(repoUrl: string): string {
  const stripped = repoUrl.replace(/^https?:\/\//, '').replace(/\.git$/, '')
  const parts = stripped.split('/').filter(Boolean)
  if (parts.length >= 3) return `${parts[1]}/${parts[2]}`
  return parts[parts.length - 1] ?? repoUrl
}

function WorkspaceSwitcher() {
  const { data: integrations } = useIntegrations()
  const githubInt = integrations?.find((i) => i.provider_name === 'GitHub')
  const repoUrl =
    typeof githubInt?.config?.repo_url === 'string' && githubInt.config.repo_url
      ? (githubInt.config.repo_url as string)
      : null

  return (
    <div className="px-[14px] pt-[14px] pb-[10px]">
      <div
        className="cd-section-label cd-section-label--quiet"
        style={{ marginBottom: 6 }}
      >
        Current scope
      </div>
      {repoUrl ? (
        <button
          type="button"
          aria-label={`Workspace: ${repoDisplayName(repoUrl)}`}
          title={repoDisplayName(repoUrl)}
          className={`w-full flex items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-cd-card-hov ${focusRing}`}
          style={{
            background: 'var(--cd-card)',
            border: '1px solid var(--cd-rule)',
            color: 'var(--cd-cyan)',
            fontFamily: 'var(--cd-mono)',
            fontSize: 11.5,
            borderRadius: 2,
          }}
        >
          <span
            data-testid="sidenav-repo-initials"
            style={{ color: 'var(--cd-fg-4)' }}
          >
            ::
          </span>
          <span
            className="truncate"
            data-repo-initials={repoInitials(repoUrl, githubInt?.provider_name ?? 'GH')}
          >
            {repoDisplayName(repoUrl)}
          </span>
          <span
            className="material-symbols-outlined ml-auto"
            aria-hidden
            style={{ fontSize: 14, color: 'var(--cd-fg-4)' }}
          >
            expand_more
          </span>
        </button>
      ) : (
        <button
          type="button"
          aria-label="Workspace"
          className={`w-full flex items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-cd-card-hov ${focusRing}`}
          style={{
            background: 'var(--cd-card)',
            border: '1px solid var(--cd-rule)',
            color: 'var(--cd-fg-4)',
            fontFamily: 'var(--cd-mono)',
            fontSize: 11.5,
            borderRadius: 2,
          }}
        >
          <span style={{ color: 'var(--cd-fg-4)' }}>::</span>
          <span className="truncate">no scope connected</span>
          <span
            className="material-symbols-outlined ml-auto"
            aria-hidden
            style={{ fontSize: 14, color: 'var(--cd-fg-4)' }}
          >
            expand_more
          </span>
        </button>
      )}
    </div>
  )
}

function IssuesBadge({ count, isActive }: { count: number; isActive: boolean }) {
  if (count <= 0) return null
  return (
    <span
      data-testid="sidenav-issues-badge"
      className="font-mono font-bold"
      style={{
        fontSize: 10,
        color: isActive ? 'var(--cd-green)' : 'var(--cd-fg-4)',
        textShadow: isActive ? '0 0 6px var(--cd-green-glow)' : 'none',
      }}
    >
      {count}
    </span>
  )
}

export default function SideNav() {
  const openIssuesCount = useOpenIssuesCount()

  return (
    <aside
      className="flex flex-col w-[248px] shrink-0 sticky top-0 h-screen self-start z-10"
      style={{
        background: 'var(--cd-bg-1)',
        borderRight: '1px solid var(--cd-rule)',
      }}
    >
      {/* Wordmark only — the decorative "node id" label was cruft from
          the design handoff. Cliff's mark + sage pulse dot carries the
          brand moment on its own. */}
      <NavLink
        to="/dashboard"
        aria-label="Cliff home"
        className={`block px-[18px] pt-5 pb-[14px] ${focusRing}`}
        style={{ borderBottom: '1px solid var(--cd-rule)' }}
      >
        <CliffWordmark />
      </NavLink>

      <WorkspaceSwitcher />

      <nav
        aria-label="Primary"
        className="flex-1 min-h-0 overflow-y-auto px-2 flex flex-col gap-px"
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `cd-nav ${isActive ? 'cd-nav--active' : ''} ${focusRing}`
            }
          >
            {({ isActive }) => (
              <>
                <NavIcon name={item.icon} />
                <span className="flex-1">{item.label}</span>
                {item.to === '/issues' && (
                  <IssuesBadge count={openIssuesCount} isActive={isActive} />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer block matches the rest of the nav rail rhythm — 8px
          horizontal padding on the outer box (like the <nav> above) so
          the Settings row's hover/active background doesn't kiss the
          viewport edge, plus 6px of breathing room above and below. */}
      <div
        data-testid="sidenav-footer"
        style={{
          borderTop: '1px solid var(--cd-rule)',
          padding: '6px 8px',
        }}
      >
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `cd-nav ${isActive ? 'cd-nav--active' : ''} ${focusRing}`
          }
        >
          {({ isActive: _isActive }) => (
            <>
              <NavIcon name="settings" />
              <span className="flex-1">Settings</span>
            </>
          )}
        </NavLink>
      </div>
    </aside>
  )
}
