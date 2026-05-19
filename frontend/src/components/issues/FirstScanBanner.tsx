/**
 * First-scan banner — Q02-B24.
 *
 * A dismissible inline banner that surfaces on the Issues page when:
 *   - the user has findings,
 *   - no findings are closed yet,
 *   - they haven't dismissed the banner in this browser.
 *
 * The intent is to give post-onboarding context ("Cliff ran your first
 * scan — here's what came back") even when the brand-moment curtain on
 * the Dashboard didn't fire (e.g. mid-flow tab refresh during AI
 * provider OAuth lost the sessionStorage flag).
 *
 * Dismissal persists across reloads via localStorage. Single key, no
 * versioning — if the product ships a second onboarding surface that
 * needs reset semantics, expand later.
 */
import { useState } from 'react'

const DISMISSED_KEY = 'cliff_first_scan_dismissed'

interface Props {
  totalFindings: number
  closedCount: number
}

export function FirstScanBanner({ totalFindings, closedCount }: Props) {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true
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
      /* private mode — fall through; the in-memory dismiss still hides it */
    }
    setDismissed(true)
  }

  return (
    <div
      data-testid="first-scan-banner"
      role="status"
      style={{
        margin: '20px 28px 0',
        padding: '12px 16px',
        background: 'rgba(111,227,181,0.06)',
        borderLeft: '2px solid var(--cd-green)',
        borderRadius: 'var(--cd-r-2, 8px)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{
          fontSize: 18,
          color: 'var(--cd-green)',
          fontVariationSettings: "'FILL' 1",
        }}
        aria-hidden
      >
        check_circle
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="text-on-surface"
          style={{ fontSize: 13, fontWeight: 600 }}
        >
          Cliff ran your first scan
        </div>
        <div
          style={{
            fontSize: 12,
            color: 'var(--cd-fg-3)',
            marginTop: 2,
          }}
        >
          {totalFindings === 1
            ? '1 issue is ready to triage. Start one to see what Cliff suggests.'
            : `${totalFindings} issues are ready to triage. Start one to see what Cliff suggests.`}
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
