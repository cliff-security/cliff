import { NavLink } from 'react-router'
import { useIntegrations, useOpenIssuesCount } from '@/api/hooks'

/**
 * Primary navigation rail (PRD-0006 / IMPL-0008).
 *
 * 224px named rail matching ``IPSideNav`` from
 * ``frontend/mockups/claude-design/PRD-0006/issues-page/chrome.jsx``:
 *  - Logo block (shield_lock + OpenSec wordmark)
 *  - Workspace switcher (single-repo in alpha; click is a no-op)
 *  - Two named primary nav items: Dashboard, Issues (with count badge)
 *  - Footer with labeled Settings row, separated by a hairline
 *
 * Three ``1px solid`` borders are explicit Serene Sentinel design
 * exceptions, all per the IPSideNav source: the aside's right edge, the
 * workspace-switcher card, and the footer top divider.
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

const navItemBase =
  'flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] font-medium transition-colors'
const navItemActive = 'bg-surface-container-highest text-on-surface font-semibold'
const navItemInactive = 'text-on-surface-variant hover:bg-surface-container'
const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-0'

function NavIcon({ name, filled }: { name: string; filled: boolean }) {
  return (
    <span
      className="material-symbols-outlined"
      aria-hidden
      style={{
        fontSize: 18,
        fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'wght' 400, 'GRAD' 0, 'opsz' 24`,
      }}
    >
      {name}
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
      // ["github.com", "linear", "billing"] → owner=parts[1], repo=parts[2]
      if (parts.length >= 3) {
        const owner = parts[1]
        const repo = parts[2]
        return `${owner[0] ?? ''}${repo[0] ?? ''}`.toUpperCase()
      }
    } catch {
      // fall through to the provider-name fallback
    }
  }
  return providerName.slice(0, 2).toUpperCase()
}

function repoDisplayName(repoUrl: string): string {
  // CEO override of the chrome.jsx mock: render in GitHub's native
  // `owner/repo` style (galanko/OpenSec) instead of `owner-repo`
  // (galanko-OpenSec) so the card reads instantly as a repo identifier.
  const stripped = repoUrl.replace(/^https?:\/\//, '').replace(/\.git$/, '')
  const parts = stripped.split('/').filter(Boolean)
  if (parts.length >= 3) return `${parts[1]}/${parts[2]}`
  return parts[parts.length - 1] ?? repoUrl
}

function repoUrlHint(repoUrl: string): string {
  return repoUrl.replace(/^https?:\/\//, '').replace(/\.git$/, '')
}

function WorkspaceSwitcher() {
  const { data: integrations } = useIntegrations()
  const githubInt = integrations?.find((i) => i.provider_name === 'GitHub')
  const repoUrl =
    typeof githubInt?.config?.repo_url === 'string' && githubInt.config.repo_url
      ? (githubInt.config.repo_url as string)
      : null

  // 1px solid border — design exception per chrome.jsx IPSideNav.
  const baseClasses =
    'mx-3 mb-4 flex items-center justify-between rounded-lg px-2.5 py-2 transition-colors border border-outline-variant'

  if (!repoUrl) {
    return (
      <button
        type="button"
        aria-label="Workspace"
        className={`${baseClasses} hover:bg-surface-container ${focusRing}`}
      >
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="rounded-md flex items-center justify-center font-mono font-bold text-[10px] bg-surface-container-high text-on-surface-variant"
            style={{ width: 22, height: 22 }}
            aria-hidden
          >
            —
          </div>
          <div className="min-w-0 text-left">
            <div className="text-[12px] font-semibold text-on-surface-variant truncate">
              No repo connected
            </div>
            <div className="text-[10px] text-on-surface-variant truncate">
              Add a GitHub integration
            </div>
          </div>
        </div>
        <span
          className="material-symbols-outlined text-on-surface-variant"
          aria-hidden
          style={{ fontSize: 14 }}
        >
          unfold_more
        </span>
      </button>
    )
  }

  const initials = repoInitials(repoUrl, githubInt?.provider_name ?? 'GH')
  const name = repoDisplayName(repoUrl)
  const hint = repoUrlHint(repoUrl)

  return (
    <button
      type="button"
      aria-label={`Workspace: ${name}`}
      className={`${baseClasses} hover:bg-surface-container ${focusRing}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <div
          className="rounded-md flex items-center justify-center font-mono font-bold text-[10px] bg-tertiary-container text-on-tertiary-container"
          style={{ width: 22, height: 22 }}
          aria-hidden
        >
          {initials}
        </div>
        <div className="min-w-0 text-left">
          <div className="text-[12px] font-semibold text-on-surface truncate">
            {name}
          </div>
          <div className="text-[10px] text-on-surface-variant truncate">
            {hint}
          </div>
        </div>
      </div>
      <span
        className="material-symbols-outlined text-on-surface-variant"
        aria-hidden
        style={{ fontSize: 14 }}
      >
        unfold_more
      </span>
    </button>
  )
}

function IssuesBadge({ count, isActive }: { count: number; isActive: boolean }) {
  if (count <= 0) return null
  const tone = isActive
    ? 'bg-primary text-on-primary'
    : 'bg-surface-container-high text-on-surface-variant'
  return (
    <span
      data-testid="sidenav-issues-badge"
      className={`font-mono font-semibold rounded-full text-[10px] min-w-[20px] text-center px-1.5 py-px ${tone}`}
    >
      {count}
    </span>
  )
}

export default function SideNav() {
  const openIssuesCount = useOpenIssuesCount()

  return (
    <aside
      // 1px solid right border — design exception per chrome.jsx IPSideNav.
      className="flex flex-col w-56 shrink-0 bg-surface-container-low border-r border-outline-variant min-h-screen"
    >
      {/* Logo block */}
      <NavLink
        to="/dashboard"
        aria-label="OpenSec home"
        className={`flex items-center gap-2.5 px-5 py-5 ${focusRing}`}
      >
        <div
          className="rounded-xl flex items-center justify-center bg-primary text-on-primary"
          style={{ width: 32, height: 32 }}
        >
          <span
            data-testid="sidenav-logo-icon"
            className="material-symbols-outlined"
            aria-hidden
            style={{
              fontSize: 20,
              fontVariationSettings: `'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 24`,
            }}
          >
            shield_lock
          </span>
        </div>
        <span className="font-headline font-extrabold text-[15px] tracking-tight text-on-surface">
          OpenSec
        </span>
      </NavLink>

      <WorkspaceSwitcher />

      <nav aria-label="Primary" className="flex-1 px-2.5 space-y-0.5">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `${navItemBase} ${isActive ? navItemActive : navItemInactive} ${focusRing}`
            }
          >
            {({ isActive }) => (
              <>
                <NavIcon name={item.icon} filled={isActive} />
                <span className="flex-1">{item.label}</span>
                {item.to === '/issues' && (
                  <IssuesBadge count={openIssuesCount} isActive={isActive} />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* 1px solid top border — design exception per chrome.jsx IPSideNav. */}
      <div
        data-testid="sidenav-footer"
        className="p-2.5 border-t border-outline-variant"
      >
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `${navItemBase} ${isActive ? navItemActive : navItemInactive} ${focusRing}`
          }
        >
          {({ isActive }) => (
            <>
              <NavIcon name="settings" filled={isActive} />
              <span className="flex-1">Settings</span>
            </>
          )}
        </NavLink>
      </div>
    </aside>
  )
}
