import { useEffect, useState } from 'react'
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

  // Local 15-minute countdown anchored to the connect response. Updates
  // every second so the user sees a live timer; backend remains the
  // source of truth for actual expiry via the polling status.
  const [expiresAtMs] = useState(() => Date.now() + connect.expires_in * 1000)
  const [remainingMs, setRemainingMs] = useState(connect.expires_in * 1000)
  useEffect(() => {
    const id = window.setInterval(() => {
      setRemainingMs(Math.max(0, expiresAtMs - Date.now()))
    }, 1000)
    return () => window.clearInterval(id)
  }, [expiresAtMs])

  useEffect(() => {
    if (status?.status === 'connected') {
      // Small delay so the user sees the success state before dismissal.
      const id = window.setTimeout(onDismiss, 600)
      return () => window.clearTimeout(id)
    }
    return undefined
  }, [status?.status, onDismiss])

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
              className="text-lg font-semibold tracking-tight text-on-surface"
            >
              Authorize OpenSec on this device
            </h3>
            <p className="text-sm text-on-surface-variant mt-1">
              Open GitHub and enter the code below to finish connecting.
            </p>
          </div>
        </div>

        {!terminal && (
          <>
            {/* Step 1 — copy the code */}
            <div className="rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 1 · Copy this code
              </p>
              <div className="flex items-center justify-between gap-3">
                <code className="font-mono text-3xl font-bold tracking-[0.3em] text-on-surface select-all">
                  {connect.user_code}
                </code>
                <button
                  type="button"
                  aria-label="Copy code"
                  onClick={handleCopyCode}
                  className="inline-flex items-center gap-1.5 rounded-md bg-surface-container-lowest px-3 py-2 text-xs font-semibold text-on-surface-variant hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-sm">
                    content_copy
                  </span>
                  Copy
                </button>
              </div>
            </div>

            {/* Step 2 — authorize on GitHub (the prominent action) */}
            <div className="mt-3 rounded-xl bg-surface-container-low p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                Step 2 · Paste it on GitHub to authorize
              </p>
              <a
                href={connect.verification_uri}
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-5 py-3 text-base font-semibold text-on-primary hover:bg-primary/90 transition-colors"
              >
                <span className="material-symbols-outlined text-xl">
                  open_in_new
                </span>
                Authorize on GitHub
              </a>
              <p className="text-xs text-on-surface-variant mt-3 text-center">
                Opens <span className="font-mono">github.com/login/device</span>{' '}
                in a new tab. Paste the code above, click Authorize, and come
                back here — we'll detect it automatically.
              </p>
            </div>

            <p className="mt-4 text-xs text-on-surface-variant text-center">
              Code expires in{' '}
              <span className="font-mono font-semibold">{timer}</span>
              {status && (
                <>
                  {' · '}
                  <span aria-live="polite">
                    {statusLabel(status.status)}
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
              Continue in background
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function statusLabel(status: string | undefined): string {
  switch (status) {
    case 'installation_pending':
      return 'Waiting for install...'
    case 'device_pending':
      return 'Waiting for authorization...'
    case 'rate_limited':
      return 'Slowing down...'
    case 'connected':
      return 'Connected'
    default:
      return 'Polling...'
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
