import { GithubAppConnectButton } from './GithubAppConnectButton'

/**
 * One-line banner shown above the configured-integrations list when:
 * - The shared GitHub App onboarding surface is configured on this
 *   instance (env var ``OPENSEC_GITHUB_APP_CLIENT_ID`` is set), AND
 * - The user has an active PAT-style GitHub integration.
 *
 * Click → triggers the device flow exactly as a fresh "Connect GitHub"
 * would. On a successful connect the backend archives the PAT row.
 */
export function GithubAppMigrationBanner() {
  return (
    <div
      role="region"
      aria-label="GitHub App upgrade available"
      className="rounded-xl bg-surface-container-low p-4 mb-4 flex items-center justify-between gap-4"
    >
      <div className="flex items-start gap-3 min-w-0">
        <div className="w-9 h-9 rounded-lg bg-surface-container-lowest flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-primary">
            auto_awesome
          </span>
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-on-surface">
            Switch to the new GitHub App
          </p>
          <p className="text-xs text-on-surface-variant mt-0.5">
            One-click install, no token to manage. Your existing token keeps
            working until you switch — and we'll keep it in storage afterwards
            in case you want to switch back.
          </p>
        </div>
      </div>
      <GithubAppConnectButton
        label="Switch"
        className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-60 flex-shrink-0"
      />
    </div>
  )
}
