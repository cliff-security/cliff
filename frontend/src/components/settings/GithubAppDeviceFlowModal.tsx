import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  useGithubAppPollNow,
  useGithubAppStatus,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'

/**
 * Modal that walks the user through the device flow once we have a
 * device code from POST /connect. Polls /status every 2s.
 *
 * One phase (ADR-0048): device authorization. The user shows the
 * one-time code, pastes it on github.com/login/device, authorizes the
 * App. The moment the backend's poller catches the user access token
 * the status flips to ``connected`` and this modal dismisses — the
 * token IS the connection, there is no installation-discovery step.
 *
 * Installing the Cliff GitHub App on a repo is a separate concern,
 * surfaced as an always-available "install or manage the App" link on
 * the Integrations page — not a step inside this modal.
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
  const qc = useQueryClient()

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
      // Refresh the integrations list — the backend creates the github
      // integration row when the device flow's poll resolves to
      // connected, but the query that drives Settings (and the picker
      // visibility) doesn't auto-revalidate. Without this, the user
      // sees the modal close successfully but the configured card +
      // repo picker don't appear until a hard refresh.
      qc.invalidateQueries({ queryKey: ['integrations'] })
      qc.invalidateQueries({ queryKey: ['integrations', 'health'] })
      // Small delay so the user sees the success state before dismissal.
      const id = window.setTimeout(onDismiss, 600)
      return () => window.clearTimeout(id)
    }
    return undefined
  }, [status?.status, onDismiss, qc])

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

  // `connected` is its own phase: the flow succeeded and `onDismiss`
  // fires after a 600 ms grace window. During that window we show a
  // success confirmation, not the device-code steps — otherwise the
  // user could re-open the GitHub device page after already finishing.
  const connected = status?.status === 'connected'
  const terminal =
    status?.status === 'expired' ||
    status?.status === 'denied' ||
    status?.status === 'error' ||
    remainingMs <= 0

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
    // Side effects of the Step 3 click. Navigation itself comes from
    // the anchor's native target=_blank — that path is gesture-trusted
    // and survives popup blockers, whereas a paired window.open()
    // (what we used to do) gets silently killed.
    void copyCode()
    setAuthorizeOpened(true)
  }

  const showDeviceSteps = !terminal && !connected

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
              Install Cliff on GitHub
            </h3>
            <p className="text-sm text-on-surface-variant mt-1">
              Two parts: install the Cliff App on the repo you want to
              secure, then authorize this device by pasting the code on
              GitHub. We'll detect both automatically.
            </p>
          </div>
        </div>

        {showDeviceSteps && (
          <>
            {/* Step 1 — install the App on the user's repo. The device
                flow alone only issues a user access token; the App
                still has to be installed for push access (PR creation)
                and for the App to show up in the user's GitHub Apps
                list. We don't wait for the install callback (Bug B02 —
                the setup_url is globally pinned to one Cliff port), so
                this is a fire-and-forget "go install on GitHub" link.
                The install_url already carries a CSRF ``state``. */}
            <div className="rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 1 · Install the App on your repo
              </p>
              <a
                href={connect.install_url}
                target="_blank"
                rel="noreferrer"
                data-testid="device-flow-install-link"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-surface-container-lowest px-5 py-3 text-sm font-semibold text-on-surface hover:bg-surface-container transition-colors"
              >
                <span className="material-symbols-outlined text-lg">
                  open_in_new
                </span>
                Open GitHub to install
              </a>
              <p className="text-xs text-on-surface-variant mt-3 text-center">
                Pick the repo you want Cliff to secure, then click
                Install. Come back here for step 2.
              </p>
            </div>

            {/* Step 2 — the code, prominently displayed. Clicking the
                Copy button copies it manually; clicking Authorize below
                also copies + opens GitHub. */}
            <div className="mt-3 rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 2 · Your one-time code
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

            {/* Step 3 — opens GitHub AND copies the code (one click,
                two effects). */}
            <div className="mt-3 rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 3 · Paste it on GitHub to authorize
              </p>
              <a
                href={connect.verification_uri}
                target="_blank"
                rel="noreferrer"
                onClick={handleAuthorize}
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

        {connected && (
          <div className="rounded-xl bg-surface-container-low p-5 text-center">
            <span className="material-symbols-outlined text-3xl text-primary">
              check_circle
            </span>
            <p className="text-sm font-semibold text-on-surface mt-1">
              Connected to GitHub
            </p>
          </div>
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

        {!terminal && !connected && (
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
