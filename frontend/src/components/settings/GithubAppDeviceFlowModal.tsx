import { useEffect, useRef, useState } from 'react'
import {
  useGithubAppInstallations,
  useGithubAppPollNow,
  useGithubAppSelectInstallation,
  useGithubAppStatus,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'

/**
 * Modal that walks the user through the device flow once we have a
 * device code from POST /connect. Polls /status every 2s.
 *
 * Two-phase flow (ADR-0048 — collapsed, no install-tab first):
 *
 *   1. Device authorization — show the one-time code, the user pastes
 *      it on github.com/login/device. Status sits in
 *      ``installation_pending`` (no github_login yet).
 *   2. Installation discovery — once the device is authorized the
 *      backend discovers the GitHub App installation from the user
 *      access token. If exactly one is found it connects automatically;
 *      if none, this modal shows an "Install the Cliff GitHub App"
 *      affordance; if several, a picker. This phase is
 *      ``installation_pending`` *with* a github_login set.
 *
 * GitHub does NOT honour ``?user_code=`` for pre-filling the device
 * page (we tested it — the param is stripped on the redirect to
 * /select_account). The best we can do is:
 *
 *   1. Show the code prominently in big mono type.
 *   2. Auto-copy it to the clipboard the moment the user clicks
 *      Authorize, so on the github.com page they paste with one
 *      keystroke instead of typing 8 chars.
 *   3. Tell them clearly that we copied it for them.
 *
 * Design system: tonal layering, no `1px solid` borders, sentence
 * case, Material Symbols for icons.
 */
const COUNTDOWN_VISIBLE_BELOW_MS = 2 * 60 * 1000 // start showing under 2 min

export function GithubAppDeviceFlowModal({
  connect,
  onDismiss,
  onTryAgain,
}: {
  connect: DeviceFlowConnectResponse
  onDismiss: () => void
  onTryAgain: () => void
}) {
  const { data: status } = useGithubAppStatus({ enabled: true })
  const pollNow = useGithubAppPollNow()

  const [expiresAtMs] = useState(() => Date.now() + connect.expires_in * 1000)
  const [remainingMs, setRemainingMs] = useState(connect.expires_in * 1000)
  useEffect(() => {
    const id = window.setInterval(() => {
      setRemainingMs(Math.max(0, expiresAtMs - Date.now()))
    }, 1000)
    return () => window.clearInterval(id)
  }, [expiresAtMs])

  // Tab-return detection: when the user clicks "Authorize on GitHub"
  // we open a new tab; once they come back we know they at least
  // attempted the authorize step and the modal should reflect that
  // instead of generic "Waiting for authorization...".
  const [authorizeOpened, setAuthorizeOpened] = useState(false)
  const [returnedFromAuthorize, setReturnedFromAuthorize] = useState(false)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!authorizeOpened) return
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        setReturnedFromAuthorize(true)
        // Nudge the backend to poll RIGHT NOW instead of waiting up
        // to the GitHub-supplied interval (5-60s after a slow_down).
        // The mutation is fire-and-forget; if it errors the regular
        // background poll loop still catches up on its own schedule.
        pollNow.mutate()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
    // pollNow's identity is stable per render; depending on it would
    // re-arm the listener on every keystroke. Linter exception is
    // intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authorizeOpened])

  useEffect(() => {
    if (status?.status === 'connected') {
      // Small delay so the user sees the success state before dismissal.
      const id = window.setTimeout(onDismiss, 600)
      return () => window.clearTimeout(id)
    }
    return undefined
  }, [status?.status, onDismiss])

  // Move focus to the modal heading on mount + Escape to dismiss. Both
  // are basic dialog hygiene that screen readers + keyboard users
  // depend on.
  const headingRef = useRef<HTMLHeadingElement | null>(null)
  useEffect(() => {
    headingRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onDismiss])

  const remainingMinutes = Math.floor(remainingMs / 60_000)
  const remainingSeconds = Math.floor((remainingMs % 60_000) / 1000)
  const timer = `${remainingMinutes}:${remainingSeconds.toString().padStart(2, '0')}`

  // ADR-0048 — the device flow is authorized but no installation is
  // bound yet (the backend discovered zero, or more than one). The
  // github_login is what tells this phase apart from the pre-auth
  // device-code phase: it's only set after the token is in hand.
  const awaitingInstall =
    status?.status === 'installation_pending' && !!status?.github_login

  // The device-code countdown is meaningless once the code is consumed
  // (i.e. once we're awaiting the install), so it can't terminate us there.
  const terminal =
    !awaitingInstall &&
    (status?.status === 'expired' ||
      status?.status === 'denied' ||
      status?.status === 'error' ||
      remainingMs <= 0)

  const copyCode = async () => {
    try {
      await navigator.clipboard?.writeText(connect.user_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard write can fail (insecure context, permission); the
      // code is still visible on screen so the user can copy manually.
    }
  }

  const handleAuthorize = () => {
    // Copy code → open authorize tab. Order matters: writeText must
    // happen synchronously inside the click handler to count as a
    // user gesture.
    void copyCode()
    setAuthorizeOpened(true)
    // ``window.open`` is also gated by user gesture; keep this on the
    // synchronous path of the click handler. Fallback href on the link
    // covers cases where the popup blocker still trips.
    window.open(connect.verification_uri, '_blank', 'noopener,noreferrer')
  }

  const showDeviceSteps = !terminal && !awaitingInstall

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="github-device-flow-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4"
    >
      <div className="w-full max-w-md rounded-2xl bg-surface-container-lowest p-6 shadow-xl shadow-slate-300/40">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-surface-container-low flex items-center justify-center">
            <span className="material-symbols-outlined text-primary">
              verified_user
            </span>
          </div>
          <div className="flex-1">
            <h3
              id="github-device-flow-title"
              ref={headingRef}
              tabIndex={-1}
              className="text-lg font-semibold tracking-tight text-on-surface focus:outline-none"
            >
              {awaitingInstall
                ? 'Install the Cliff GitHub App'
                : 'Authorize Cliff on this device'}
            </h3>
            <p className="text-sm text-on-surface-variant mt-1">
              {awaitingInstall
                ? "You're authorized — now pick the account or repo Cliff should work with."
                : "Two steps: copy the code, paste it on GitHub. We'll handle the copy for you when you click Authorize."}
            </p>
          </div>
        </div>

        {showDeviceSteps && (
          <>
            {/* Step 1 — the code, prominently displayed. Clicking the
                Copy button copies it manually; clicking Authorize below
                also copies + opens GitHub. */}
            <div className="rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 1 · Your one-time code
              </p>
              <div className="flex items-center justify-between gap-3">
                <code className="font-mono text-3xl font-bold tracking-[0.3em] text-on-surface select-all">
                  {connect.user_code}
                </code>
                <button
                  type="button"
                  aria-label="Copy code"
                  onClick={copyCode}
                  className="inline-flex items-center gap-1.5 rounded-md bg-surface-container-lowest px-3 py-2 text-xs font-semibold text-on-surface-variant hover:text-on-surface transition-colors min-h-[36px]"
                >
                  <span className="material-symbols-outlined text-sm">
                    {copied ? 'check' : 'content_copy'}
                  </span>
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>

            {/* Step 2 — opens GitHub AND copies the code (one click,
                two effects). */}
            <div className="mt-3 rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 2 · Paste it on GitHub to authorize
              </p>
              <a
                href={connect.verification_uri}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                  // Drive the click through our handler so the copy +
                  // window.open both fire as part of the gesture. We
                  // still rely on the anchor's href as a fallback if
                  // popup blockers cancel the explicit open.
                  e.preventDefault()
                  handleAuthorize()
                }}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-4 text-base font-semibold text-on-primary hover:bg-primary/90 transition-colors shadow-sm shadow-primary/20"
              >
                <span className="material-symbols-outlined text-xl">
                  open_in_new
                </span>
                Copy code &amp; open GitHub
              </a>
              <p className="text-xs text-on-surface-variant mt-3 text-center">
                Opens <span className="font-mono">github.com/login/device</span>
                {' '}in a new tab. Sign in if needed, click Continue, then
                paste the code (<span className="font-mono">⌘V</span> /{' '}
                <span className="font-mono">Ctrl+V</span>) and click Authorize.
                Come back here — we'll detect it automatically.
              </p>
            </div>

            <p
              className="mt-4 text-xs text-on-surface-variant text-center"
              aria-live="polite"
            >
              <span>{statusLabel(status?.status, returnedFromAuthorize)}</span>
              {remainingMs < COUNTDOWN_VISIBLE_BELOW_MS && (
                <>
                  {' · '}
                  <span aria-live="off">
                    Expires in{' '}
                    <span className="font-mono font-semibold">{timer}</span>
                  </span>
                </>
              )}
            </p>
          </>
        )}

        {awaitingInstall && (
          <GithubInstallationStep installUrl={connect.install_url} />
        )}

        {terminal && (
          <div className="rounded-xl bg-surface-container-low p-4">
            <p className="text-sm font-semibold text-on-surface">
              {terminalHeadline(status?.status, remainingMs <= 0)}
            </p>
            <p className="text-xs text-on-surface-variant mt-1">
              {terminalDetail(status?.status, status?.error)}
            </p>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={onTryAgain}
                className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors"
              >
                Try again
              </button>
              <button
                type="button"
                onClick={onDismiss}
                className="rounded-md px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {!terminal && (
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-md px-3 py-1.5 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Installation-discovery phase (ADR-0048). Once the device flow is
 * authorized the backend looks up which GitHub App installations the
 * user has. This component renders one of three states:
 *
 *   - none discovered  → "Install the Cliff GitHub App" affordance. The
 *     backend keeps polling /user/installations; the moment exactly one
 *     installation appears it connects and the modal dismisses.
 *   - exactly one      → transient — the backend is auto-connecting.
 *   - more than one    → a picker, so the user binds the right account.
 */
function GithubInstallationStep({ installUrl }: { installUrl: string }) {
  const {
    data: installations = [],
    isLoading,
    isError,
  } = useGithubAppInstallations({ enabled: true })
  const select = useGithubAppSelectInstallation()

  if (isLoading) {
    return (
      <p
        className="rounded-xl bg-surface-container-low p-5 text-sm text-on-surface-variant"
        data-testid="github-installation-loading"
      >
        Looking for your GitHub App installation…
      </p>
    )
  }

  if (isError) {
    // The lookup failed (e.g. GitHub 503). Without this branch the empty
    // `installations` default would render the "install the App"
    // affordance — hiding a real backend failure behind a wrong CTA.
    return (
      <p
        role="alert"
        className="rounded-xl bg-surface-container-low p-5 text-sm text-error"
        data-testid="github-installation-error"
      >
        Couldn't load your GitHub App installations right now. This is
        usually temporary — leave this open and we'll keep retrying.
      </p>
    )
  }

  if (installations.length === 0) {
    return (
      <div
        className="rounded-xl bg-surface-container-low p-5"
        data-testid="github-installation-install"
      >
        <p className="text-sm text-on-surface">
          One more step — install the Cliff GitHub App on the account or
          repository you want to secure.
        </p>
        <a
          href={installUrl}
          target="_blank"
          rel="noreferrer"
          data-testid="github-installation-install-link"
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-4 text-base font-semibold text-on-primary hover:bg-primary/90 transition-colors shadow-sm shadow-primary/20"
        >
          <span className="material-symbols-outlined text-xl">open_in_new</span>
          Install the Cliff GitHub App
        </a>
        <p className="mt-3 text-center text-xs text-on-surface-variant">
          Opens github.com in a new tab. Keep this tab open — we'll detect
          the install automatically and finish connecting.
        </p>
      </div>
    )
  }

  if (installations.length === 1) {
    return (
      <p
        className="rounded-xl bg-surface-container-low p-5 text-sm text-on-surface-variant"
        data-testid="github-installation-finishing"
      >
        Found your installation — finishing up…
      </p>
    )
  }

  return (
    <div
      className="rounded-xl bg-surface-container-low p-5"
      data-testid="github-installation-picker"
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
        Choose an account
      </p>
      <p className="text-sm text-on-surface-variant mb-3">
        The Cliff GitHub App is installed on more than one account. Pick the
        one to connect to this Cliff.
      </p>
      <ul className="flex flex-col gap-2">
        {installations.map((inst) => (
          <li key={inst.installation_id}>
            <button
              type="button"
              data-testid={`github-installation-option-${inst.installation_id}`}
              onClick={() => select.mutate(inst.installation_id)}
              disabled={select.isPending}
              className="flex w-full items-center justify-between gap-3 rounded-lg bg-surface-container-lowest px-4 py-3 text-left text-sm text-on-surface hover:bg-surface-container transition-colors disabled:opacity-60"
            >
              <span className="font-semibold">{inst.account_login}</span>
              <span className="text-xs text-on-surface-variant">
                {inst.account_type}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {select.isError && (
        <p
          role="alert"
          className="mt-3 text-xs text-error"
          data-testid="github-installation-picker-error"
        >
          Couldn't connect that account. Pick another, or try again.
        </p>
      )}
    </div>
  )
}

function statusLabel(
  status: string | undefined,
  returnedFromAuthorize: boolean,
): string {
  // Prefer the "you came back from GitHub" cue when we have it — it's
  // the most reassuring copy in the window between authorize-click and
  // the next polling tick that catches the access token.
  if (returnedFromAuthorize && status !== 'connected') {
    return 'Confirming with GitHub…'
  }
  switch (status) {
    case 'installation_pending':
    case 'device_pending':
      return 'Waiting for authorization…'
    case 'rate_limited':
      return 'Slowing down…'
    case 'connected':
      return 'Connected'
    default:
      return 'Getting your device code ready…'
  }
}

function terminalHeadline(status: string | undefined, expired: boolean): string {
  if (expired || status === 'expired') return 'The code expired.'
  if (status === 'denied') return 'Authorization was canceled.'
  return 'Something went wrong.'
}

function terminalDetail(
  status: string | undefined,
  error: string | null | undefined,
): string {
  if (status === 'expired')
    return 'Codes only stay valid for 15 minutes. Start a new one to try again.'
  if (status === 'denied')
    return 'You canceled on the GitHub authorization screen. No problem — restart whenever you are ready.'
  return error ?? 'Restart the connect flow to try again.'
}
