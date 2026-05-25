import { useMemo, useState } from 'react'
import type { RepoOption } from '@/api/onboarding'

export interface RepoPickerProps {
  repos: RepoOption[]
  /** Disabled while a parent submission is in flight (e.g. verifying a pick). */
  busy?: boolean
  onSelect: (repo: RepoOption) => void
  /** Install URL passed through from the registry / repos endpoint, used
   *  for the "Install Cliff on <owner>" hint on rows where the App isn't
   *  installed on this repo's owner. When absent the hint degrades to a
   *  read-only "App not installed on this owner" tag. */
  installUrl?: string | null
}

/**
 * Phase B of onboarding's "Connect your project" — rendered after the user
 * pastes a PAT in phase A and the backend returns the repos that token can
 * see. Read-only repos (``can_push=false``) render disabled with a tooltip
 * so the user doesn't pick one and hit the ``missing_repo_scope`` error
 * three steps later.
 *
 * Repos where ``app_installed=false`` (visible via org membership but the
 * Cliff App isn't installed on the owner) render disabled too, with a
 * sibling "Install Cliff on <owner>" link. The user can read the repo via
 * their token but Cliff can't push to it — picking it leads to a dead-end
 * three steps later otherwise.
 */
export default function RepoPicker({
  repos,
  busy = false,
  onSelect,
  installUrl,
}: RepoPickerProps) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return repos
    return repos.filter((r) => r.full_name.toLowerCase().includes(q))
  }, [repos, query])

  return (
    <div data-testid="repo-picker">
      <label className="block mb-3">
        <span className="sr-only">Filter repositories</span>
        <input
          type="search"
          autoComplete="off"
          autoFocus
          placeholder="Search your repositories…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full px-4 py-3 rounded-lg bg-surface-container-lowest shadow-sm border-0 ring-0 focus:ring-2 focus:ring-primary/30 focus:outline-none text-sm"
        />
      </label>

      <ul
        role="listbox"
        aria-label="Repositories"
        className="max-h-80 overflow-y-auto rounded-lg bg-surface-container-lowest shadow-sm divide-y divide-outline-variant/10"
      >
        {filtered.length === 0 ? (
          <li className="px-4 py-6 text-sm text-on-surface-variant text-center">
            No repositories match "{query}".
          </li>
        ) : (
          filtered.map((repo) => {
            const appMissing = repo.app_installed === false
            const disabled = !repo.can_push || appMissing || busy
            const owner = repo.full_name.split('/')[0] || repo.full_name
            const title = appMissing
              ? `Cliff App isn't installed on ${owner}. Install it first.`
              : repo.can_push
                ? undefined
                : "Token doesn't have push access to this repo."
            return (
              <li
                key={repo.full_name}
                role="option"
                aria-selected="false"
                className="flex items-center"
              >
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onSelect(repo)}
                  title={title}
                  className="flex-1 px-4 py-3 flex items-center gap-3 text-left hover:bg-surface-container disabled:hover:bg-transparent disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:bg-surface-container"
                >
                  <span
                    className="material-symbols-outlined text-on-surface-variant flex-shrink-0"
                    aria-hidden="true"
                  >
                    {repo.private ? 'lock' : 'public'}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-sm font-semibold text-on-surface truncate">
                      {repo.full_name}
                    </span>
                    <span className="block text-xs text-on-surface-variant mt-0.5">
                      {repo.private ? 'Private' : 'Public'} · {repo.default_branch}
                      {appMissing
                        ? ` · App not installed on ${owner}`
                        : !repo.can_push && ' · read-only'}
                    </span>
                  </span>
                </button>
                {appMissing && installUrl && (
                  <a
                    href={installUrl}
                    target="_blank"
                    rel="noreferrer"
                    data-testid="repo-picker-install-link"
                    className="flex-shrink-0 mr-3 inline-flex items-center gap-1 rounded-md bg-surface-container-low px-2 py-1.5 text-xs font-semibold text-primary hover:bg-surface-container transition-colors"
                  >
                    <span
                      className="material-symbols-outlined text-sm"
                      aria-hidden="true"
                    >
                      open_in_new
                    </span>
                    Install on {owner}
                  </a>
                )}
              </li>
            )
          })
        )}
      </ul>
    </div>
  )
}
