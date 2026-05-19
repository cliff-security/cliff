/**
 * Dismissible banner that surfaces on the Issues page after a fresh
 * onboarding scan, when the user has findings but hasn't closed any
 * yet. Dismissal persists in localStorage.
 *
 * The Dashboard's PostOnboardingCurtain owns the brand moment for the
 * happy onboarding path. This banner covers the interrupted-onboarding
 * case where the curtain's sessionStorage flag was never set (e.g.
 * tab refresh during AI provider OAuth).
 */
import { useState } from 'react'

const DISMISSED_KEY = 'cliff_first_scan_dismissed'

interface Props {
  totalFindings: number
  closedCount: number
}

export function FirstScanBanner({ totalFindings, closedCount }: Props) {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(DISMISSED_KEY) === '1'
    } catch {
      return false
    }
  })

  if (dismissed) return null
  if (totalFindings === 0) return null
  if (closedCount > 0) return null

  const handleDismiss = () => {
    try {
      window.localStorage.setItem(DISMISSED_KEY, '1')
    } catch {
      // Private mode — the in-memory dismiss still hides it.
    }
    setDismissed(true)
  }

  const message =
    totalFindings === 1
      ? '1 issue is ready to triage. Start one to see what Cliff suggests.'
      : `${totalFindings} issues are ready to triage. Start one to see what Cliff suggests.`

  return (
    <div
      data-testid="first-scan-banner"
      role="status"
      className="mx-7 mt-5 flex items-center gap-3 rounded-lg bg-tertiary-container/30 px-4 py-3"
      style={{ borderLeft: '2px solid var(--cd-green)' }}
    >
      <span
        className="material-symbols-outlined text-tertiary"
        style={{ fontSize: 18, fontVariationSettings: "'FILL' 1" }}
        aria-hidden
      >
        check_circle
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-semibold text-on-surface">
          Cliff ran your first scan
        </div>
        <div className="text-[12px] mt-0.5 text-on-surface-variant">
          {message}
        </div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        className="cd-btn cd-btn--ghost cd-btn--sm"
        data-testid="first-scan-banner-dismiss"
      >
        Got it
      </button>
    </div>
  )
}
