import { useEffect, useRef, useState } from 'react'
import {
  useGithubAppStatus,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'

/**
 * Modal that walks the user through the device flow once we have a
 * device code from POST /connect. Polls /status every 2s until a
 * terminal state arrives, then either dismisses (success) or surfaces
 * the error with a "Try again" affordance.
 *
 * Design system: tonal layering, no `1px solid` borders, sentence case,
 * Material Symbols for icons.
 */
const COUNTDOWN_VISIBLE_BELOW_MS = 2 * 60 * 1000  // start showing under 2 min

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
  useEffect(() => {
    if (!authorizeOpened) return
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        setReturnedFromAuthorize(true)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
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

  const terminal = status?.status === 'expired'
    || status?.status === 'denied'
    || status?.status === 'error'
    || remainingMs <= 0

  const handleCopyCode = () => {
    void navigator.clipboard?.writeText(connect.user_code)
  }

  // GitHub's /login/device page accepts ``?user_code=AAAA-BBBB`` to
  // pre-fill the input. With this the user lands on a one-click
  // Authorize page — no copy/paste needed. Single biggest UX win we
  // could make in this flow.
  const authorizeUrl = `${connect.verification_uri}?user_code=${encodeURIComponent(
    connect.user_code,
  )}`

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
              Authorize OpenSec on this device
            </h3>
            <p className="text-sm text-on-surface-variant mt-1">
              Click the button below to confirm on GitHub. We pre-fill the
              code for you.
            </p>
          </div>
        </div>

        {!terminal && (
          <>
            {/* Step 2 — primary action. Pre-filled URL means the user
                doesn't need to copy/paste; we keep Step 1 below as a
                fallback in case the pre-fill ever fails. */}
            <a
              href={authorizeUrl}
              target="_blank"
              rel="noreferrer"
              onClick={() => setAuthorizeOpened(true)}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-4 text-base font-semibold text-on-primary hover:bg-primary/90 transition-colors shadow-sm shadow-primary/20"
            >
              <span className="material-symbols-outlined text-xl">
                open_in_new
              </span>
              Authorize on GitHub
            </a>
            <p className="text-xs text-on-surface-variant mt-2 text-center">
              Opens <span className="font-mono">github.com/login/device</span>
              {' '}with the code already filled in. Click Authorize there,
              then come back — we'll detect it automatically.
            </p>

            {/* Step 1 — code, kept as a fallback (some users may want to
                copy/paste manually if the pre-filled link is blocked). */}
            <details className="mt-5 rounded-xl bg-surface-container-low p-4">
              <summary className="cursor-pointer text-xs font-semibold text-on-surface-variant select-none">
                Need to enter the code manually? Copy it here
              </summary>
              <div className="mt-3 flex items-center justify-between gap-3">
                <code className="font-mono text-2xl font-bold tracking-[0.3em] text-on-surface select-all">
                  {connect.user_code}
                </code>
                <button
                  type="button"
                  aria-label="Copy code"
                  onClick={handleCopyCode}
                  className="inline-flex items-center gap-1.5 rounded-md bg-surface-container-lowest px-3 py-2 text-xs font-semibold text-on-surface-variant hover:text-on-surface transition-colors min-h-[36px]"
                >
                  <span className="material-symbols-outlined text-sm">
                    content_copy
                  </span>
                  Copy
                </button>
              </div>
            </details>

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
      return 'Waiting for install…'
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
