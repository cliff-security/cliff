import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import RepoPicker from '@/components/onboarding/RepoPicker'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'
import {
  onboardingApi,
  OnboardingApiError,
  type OnboardingRepoResponse,
  type RepoOption,
} from '@/api/onboarding'

const MISSING_REPO_SCOPE_CODE = 'missing_repo_scope'

type FlowState =
  | { kind: 'listingRepos' }
  | { kind: 'tokenError'; error: OnboardingApiError }
  | { kind: 'pickRepo'; repos: RepoOption[] }
  | { kind: 'verifyingPick'; repos: RepoOption[]; chosen: string }
  | { kind: 'pickError'; repos: RepoOption[]; error: OnboardingApiError }

export interface RepoPickerFlowProps {
  /**
   * Called once a repo has been verified by the backend. The parent owns
   * what happens next — onboarding shows a celebratory card and auto-
   * advances to the AI step; the settings dialog closes itself and
   * refreshes the integrations list.
   */
  onConnected: (response: OnboardingRepoResponse) => void
  /**
   * Override the default token-error UI. Receives the error and a
   * ``retry`` callback that re-runs the vault list. Onboarding uses this
   * to surface "open Settings to disconnect" + a PAT fallback link.
   */
  renderTokenError?: (
    error: OnboardingApiError,
    retry: () => void,
  ) => ReactNode
  /**
   * Optional caption shown above the picker. Defaults to "Pick the
   * repository to secure." — onboarding overrides to nothing because the
   * page already has a heading.
   */
  caption?: string
  /** Optional secondary control rendered to the right of the caption. */
  topRightAction?: ReactNode
}

/**
 * Shared "list-vault-repos → pick → verify" flow used by both the
 * onboarding wizard (`/onboarding/connect`, App-flow happy path) and the
 * Settings page's "Pick a repo" dialog. Owns the small state machine
 * for listing/picking/verifying and emits ``onConnected`` once the
 * backend confirms the repo. Does NOT render success UI — parents
 * handle that themselves so each surface can present the right next
 * step.
 *
 * Assumes the user has already authorized the GitHub App and a vault
 * token exists; if not, the initial list call returns an error and we
 * surface the ``tokenError`` state.
 */
export default function RepoPickerFlow({
  onConnected,
  renderTokenError,
  caption = 'Pick the repository to secure.',
  topRightAction,
}: RepoPickerFlowProps) {
  const [state, setState] = useState<FlowState>({ kind: 'listingRepos' })
  const [manualOpen, setManualOpen] = useState(false)
  const [manualUrl, setManualUrl] = useState('')

  // Monotonic request id. Bumped on every load (mount, retry, verify).
  // Late responses from older requests are ignored — protects against
  // (a) the component unmounting before fetch settles, (b) the user
  // clicking "Try again" or picking a different repo while one is in
  // flight, (c) the manual-URL form submitting while the row-click
  // verify is still pending. CR-2 in PR #145 review.
  const requestIdRef = useRef(0)

  useEffect(
    () => () => {
      // Bump on unmount so any in-flight resolution is treated as stale.
      requestIdRef.current += 1
    },
    [],
  )

  const loadRepos = useCallback(async () => {
    const myId = ++requestIdRef.current
    setState({ kind: 'listingRepos' })
    try {
      const { repos } = await onboardingApi.listReposFromVault()
      if (requestIdRef.current !== myId) return
      setState({ kind: 'pickRepo', repos })
    } catch (err) {
      if (requestIdRef.current !== myId) return
      setState({ kind: 'tokenError', error: toOnboardingError(err) })
    }
  }, [])

  useEffect(() => {
    void loadRepos()
  }, [loadRepos])

  const verifyAndConnect = useCallback(
    async (repoUrl: string, repos: RepoOption[]) => {
      const myId = ++requestIdRef.current
      setState({ kind: 'verifyingPick', repos, chosen: repoUrl })
      try {
        const response = await onboardingApi.connectRepoFromVault(repoUrl)
        if (requestIdRef.current !== myId) return
        onConnected(response)
      } catch (err) {
        if (requestIdRef.current !== myId) return
        setState({ kind: 'pickError', repos, error: toOnboardingError(err) })
      }
    },
    [onConnected],
  )

  function handleManualSubmit(e: FormEvent, repos: RepoOption[]) {
    e.preventDefault()
    const trimmed = manualUrl.trim()
    if (!trimmed) return
    void verifyAndConnect(trimmed, repos)
  }

  if (state.kind === 'listingRepos') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-3 text-sm text-on-surface-variant py-4"
        data-testid="repo-flow-loading"
      >
        <div
          className="h-4 w-4 animate-spin rounded-full border-[2px] border-primary/30 border-t-primary"
          aria-hidden="true"
        />
        <span>Loading your repositories…</span>
      </div>
    )
  }

  if (state.kind === 'tokenError') {
    // The arrow body is a closure invoked LATER (from a click handler in
    // the parent's renderTokenError UI), not during render — the ref
    // access happens at click time. The lint rule can't see across the
    // callback boundary; silence it locally.
    // eslint-disable-next-line react-hooks/refs
    if (renderTokenError) return <>{renderTokenError(state.error, () => void loadRepos())}</>
    return (
      <div data-testid="repo-flow-token-error">
        <InlineErrorCallout
          title="We couldn't load your repositories"
          body={
            <>
              The GitHub App connection looks broken. Try again, or
              disconnect from Settings and reconnect.
            </>
          }
        />
        <div className="mt-4">
          <button
            type="button"
            onClick={() => void loadRepos()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  // pickRepo / verifyingPick / pickError all share the same picker UI.
  const pickScopeError =
    state.kind === 'pickError' && state.error.code === MISSING_REPO_SCOPE_CODE

  return (
    <div data-testid="repo-flow-pick">
      {(caption || topRightAction) && (
        <div className="mb-5 flex items-center justify-between gap-3">
          {caption ? (
            <p className="text-sm text-on-surface-variant">{caption}</p>
          ) : (
            <span />
          )}
          {topRightAction}
        </div>
      )}

      <RepoPicker
        repos={state.repos}
        busy={state.kind === 'verifyingPick'}
        onSelect={(repo) => void verifyAndConnect(repo.html_url, state.repos)}
      />

      {state.kind === 'verifyingPick' && (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 flex items-center gap-2 text-sm text-on-surface-variant"
        >
          <div
            className="h-4 w-4 animate-spin rounded-full border-[2px] border-primary/30 border-t-primary"
            aria-hidden="true"
          />
          <span>Verifying {state.chosen}…</span>
        </div>
      )}

      {state.kind === 'pickError' && (
        <InlineErrorCallout
          title={
            pickScopeError
              ? 'Your token is missing write access to that repo'
              : "We couldn't verify that repository"
          }
          body={
            pickScopeError ? (
              <>
                The token needs <span className="font-mono">Contents</span>{' '}
                and <span className="font-mono">Pull requests</span>{' '}
                (read and write) on this repository. Reinstall the GitHub
                App with the right permissions, or pick a different repo.
              </>
            ) : (
              <>{state.error.message}</>
            )
          }
        />
      )}

      <div className="mt-6">
        <button
          type="button"
          onClick={() => setManualOpen((v) => !v)}
          className="text-xs font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface px-1 py-0.5 rounded"
          aria-expanded={manualOpen}
          data-testid="manual-url-toggle"
        >
          {manualOpen ? 'Hide manual URL' : "Don't see your repo? Enter URL manually"}
        </button>
        {manualOpen && (
          <form
            onSubmit={(e) => handleManualSubmit(e, state.repos)}
            className="mt-3 flex gap-2"
          >
            <input
              type="text"
              autoComplete="off"
              value={manualUrl}
              onChange={(e) => setManualUrl(e.target.value)}
              placeholder="https://github.com/your-handle/your-project"
              className="flex-1 px-4 py-2 rounded-lg bg-surface-container-lowest shadow-sm border-0 ring-0 focus:ring-2 focus:ring-primary/30 focus:outline-none text-sm font-mono"
              data-testid="manual-url-input"
            />
            <button
              type="submit"
              disabled={!manualUrl.trim() || state.kind === 'verifyingPick'}
              className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              Verify
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

function toOnboardingError(err: unknown): OnboardingApiError {
  if (err instanceof OnboardingApiError) return err
  return new OnboardingApiError(
    err instanceof Error ? err.message : 'Unknown error',
    0,
  )
}
