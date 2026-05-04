import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import OnboardingShell from '@/components/onboarding/OnboardingShell'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'
import ConnectionResultCard from '@/components/onboarding/ConnectionResultCard'
import RepoPicker from '@/components/onboarding/RepoPicker'
import WizardNav from '@/components/onboarding/WizardNav'
import TokenHowToDialog from '@/components/completion/TokenHowToDialog'
import {
  onboardingApi,
  OnboardingApiError,
  type OnboardingRepoResponse,
  type RepoOption,
} from '@/api/onboarding'
import { onboardingStorage } from './storage'

const MISSING_REPO_SCOPE_CODE = 'missing_repo_scope'
const INVALID_TOKEN_CODE = 'invalid_token'

// How long the verified card stays on screen before we auto-advance to
// step 2. UX Spec Rev 2 calls for "a small spinner + 'Loading Step 2'
// inline hint" after verification — the delay lets the celebratory
// moment register so users see which repo got verified, while still
// owning the auto-advance. Long enough to read the repo name, short
// enough that users don't start hunting for a button.
const AUTO_ADVANCE_DELAY_MS = 1_400

type ConnectState =
  | { kind: 'enterToken' }
  | { kind: 'listingRepos' }
  | { kind: 'tokenError'; error: OnboardingApiError }
  | { kind: 'pickRepo'; repos: RepoOption[] }
  | { kind: 'verifyingPick'; repos: RepoOption[]; chosen: string }
  | { kind: 'pickError'; repos: RepoOption[]; error: OnboardingApiError }
  | { kind: 'verified'; response: OnboardingRepoResponse }

/**
 * Onboarding frames 1.1 / 1.2 / 1.3 — "Connect your project".
 *
 * Two phases:
 *   A) Token entry — paste PAT, list reachable repos.
 *   B) Repo picker — search + click, with a manual-URL fallback for users
 *      whose target repo isn't in the (capped) list.
 *
 * On success the verified card renders for ~1.4s and then the wizard
 * auto-advances to `/onboarding/ai`. UX Spec Rev 2 asked for this —
 * a manual "Continue to AI config" click is a dead-end interaction once
 * verification has succeeded, and users kept pausing there trying to
 * figure out whether something was wrong.
 */
export default function ConnectRepo() {
  const navigate = useNavigate()
  const [token, setToken] = useState('')
  const [state, setState] = useState<ConnectState>({ kind: 'enterToken' })
  const [dialogOpen, setDialogOpen] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const [manualUrl, setManualUrl] = useState('')

  // Auto-advance to AI config once the verified card has registered.
  // A dependency on ``state.kind`` is enough — ``setTimeout`` cleanup
  // kicks in if the user hits "Change" during the window.
  useEffect(() => {
    if (state.kind !== 'verified') return
    const timer = window.setTimeout(() => {
      navigate('/onboarding/ai')
    }, AUTO_ADVANCE_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [state.kind, navigate])

  const tokenScopeError =
    state.kind === 'tokenError' && state.error.code === INVALID_TOKEN_CODE
  const pickScopeError =
    state.kind === 'pickError' && state.error.code === MISSING_REPO_SCOPE_CODE

  async function handleTokenSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token.trim()) return
    setState({ kind: 'listingRepos' })
    try {
      const { repos } = await onboardingApi.listRepos({ github_token: token })
      setState({ kind: 'pickRepo', repos })
    } catch (err) {
      setState({
        kind: 'tokenError',
        error: toOnboardingError(err),
      })
    }
  }

  async function verifyAndConnect(repoUrl: string, repos: RepoOption[]) {
    setState({ kind: 'verifyingPick', repos, chosen: repoUrl })
    try {
      const response = await onboardingApi.connectRepo({
        repo_url: repoUrl,
        github_token: token,
      })
      onboardingStorage.set('assessmentId', response.assessment_id)
      onboardingStorage.set('repoUrl', response.repo_url)
      setState({ kind: 'verified', response })
    } catch (err) {
      setState({
        kind: 'pickError',
        repos,
        error: toOnboardingError(err),
      })
    }
  }

  function handleManualSubmit(e: FormEvent, repos: RepoOption[]) {
    e.preventDefault()
    const trimmed = manualUrl.trim()
    if (!trimmed) return
    void verifyAndConnect(trimmed, repos)
  }

  function resetToTokenEntry() {
    setState({ kind: 'enterToken' })
    setManualOpen(false)
    setManualUrl('')
  }

  return (
    <OnboardingShell step={1}>
      <h1 className="font-headline text-3xl font-extrabold text-on-surface mb-2">
        Connect your project
      </h1>
      <p className="text-on-surface-variant mb-8">
        Point OpenSec at the repository you'd like to secure. We use a personal
        access token so every change lands as a draft pull request you review.
      </p>

      {state.kind === 'verified' ? (
        <div
          className="motion-safe:animate-[fadeIn_220ms_ease-out]"
          data-testid="connected-confirmation"
        >
          {state.response.verified ? (
            <ConnectionResultCard
              verified={state.response.verified}
              onChange={resetToTokenEntry}
            />
          ) : (
            <div className="w-full rounded-2xl bg-surface-container-lowest shadow-sm px-6 py-6">
              <div className="flex items-start gap-3">
                <span
                  className="material-symbols-outlined text-tertiary mt-0.5"
                  aria-hidden="true"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  check_circle
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-sm font-semibold text-on-surface truncate">
                    {state.response.repo_url}
                  </p>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    Connected — ready to continue
                  </p>
                </div>
                <button
                  type="button"
                  onClick={resetToTokenEntry}
                  className="text-xs font-semibold text-on-surface-variant hover:text-on-surface px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                >
                  Change
                </button>
              </div>
            </div>
          )}
          {/*
            * UX Spec Rev 2: after verification, replace the "Continue to
            * AI config" button with a small spinner + "Loading step 2…"
            * hint so the user sees the wizard is doing the next thing for
            * them instead of waiting on a click.
            */}
          <div
            role="status"
            aria-live="polite"
            className="mt-8 flex items-center gap-3 text-sm text-on-surface-variant"
          >
            <div
              className="h-4 w-4 animate-spin rounded-full border-[2px] border-primary/30 border-t-primary"
              aria-hidden="true"
            />
            <span>Loading step 2…</span>
          </div>
        </div>
      ) : state.kind === 'pickRepo' ||
        state.kind === 'verifyingPick' ||
        state.kind === 'pickError' ? (
        <div data-testid="pick-repo-step">
          <div className="mb-5 flex items-center justify-between">
            <p className="text-sm text-on-surface-variant">
              Pick the repository to secure.
            </p>
            <button
              type="button"
              onClick={resetToTokenEntry}
              className="text-xs font-semibold text-on-surface-variant hover:text-on-surface px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              Use a different token
            </button>
          </div>

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
                  ? "Your token is missing write access to that repo"
                  : "We couldn't verify that repository"
              }
              body={
                pickScopeError ? (
                  <>
                    The token needs <span className="font-mono">Contents</span>{' '}
                    and <span className="font-mono">Pull requests</span>{' '}
                    (read and write) on this repository. Regenerate with the
                    fine-grained flow and paste it back, or pick a different repo.
                  </>
                ) : (
                  <>{state.error.message}</>
                )
              }
              action={
                pickScopeError
                  ? {
                      label: 'How to create a token',
                      href: 'https://github.com/settings/personal-access-tokens/new',
                    }
                  : undefined
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
      ) : (
        <form onSubmit={handleTokenSubmit} noValidate>
          <div className="mb-3">
            <div className="flex items-center justify-between mb-2">
              <label
                htmlFor="onboarding-pat"
                className="text-sm font-semibold text-on-surface"
              >
                GitHub personal access token
              </label>
              <button
                type="button"
                onClick={() => setDialogOpen(true)}
                className="text-xs font-medium text-primary hover:underline flex items-center gap-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface px-1 py-0.5"
              >
                <span
                  className="material-symbols-outlined text-sm"
                  aria-hidden="true"
                >
                  help_outline
                </span>
                How to create a token
              </button>
            </div>
            <input
              id="onboarding-pat"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              aria-invalid={tokenScopeError || undefined}
              placeholder="github_pat_••••••••••••••••••••••••••••"
              className={`w-full px-4 py-3 rounded-lg bg-surface-container-lowest shadow-sm border-0 ring-0 focus:ring-2 focus:outline-none text-sm font-mono ${
                tokenScopeError
                  ? 'ring-2 ring-error/40 focus:ring-error/60'
                  : 'focus:ring-primary/30'
              }`}
            />
          </div>

          {state.kind === 'tokenError' && (
            <InlineErrorCallout
              title={
                tokenScopeError
                  ? "Your token didn't work"
                  : "We couldn't reach GitHub"
              }
              body={
                tokenScopeError ? (
                  <>
                    Either the token is wrong or it doesn't have read access to
                    your repositories. Use a fine-grained token with{' '}
                    <span className="font-mono">Contents</span> and{' '}
                    <span className="font-mono">Pull requests</span> (read and
                    write).
                  </>
                ) : (
                  <>{state.error.message}</>
                )
              }
              action={
                tokenScopeError
                  ? {
                      label: 'How to create a token',
                      href: 'https://github.com/settings/personal-access-tokens/new',
                    }
                  : undefined
              }
            />
          )}

          <WizardNav
            onBack={() => navigate('/onboarding/welcome')}
            onNext={() => {
              /* handled by form submit */
            }}
            nextLabel={
              state.kind === 'listingRepos'
                ? 'Loading repositories…'
                : 'Continue'
            }
            nextDisabled={!token.trim() || state.kind === 'listingRepos'}
            nextType="submit"
          />
        </form>
      )}

      <TokenHowToDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
    </OnboardingShell>
  )
}

function toOnboardingError(err: unknown): OnboardingApiError {
  if (err instanceof OnboardingApiError) return err
  return new OnboardingApiError(
    err instanceof Error ? err.message : 'Unknown error',
    0,
  )
}
