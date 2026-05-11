/**
 * One-time banner shown to existing paste-flow users (IMPL-0011 G8).
 *
 * Auto-hides 30 days after first render. Dismissible immediately.
 */

import { useEffect, useState } from 'react'
import { useAIProviderStatus } from '@/api/aiProvider'

const SHOWN_AT_KEY = 'opensec.aiMigrationBanner.firstShownAt'
const DISMISSED_KEY = 'opensec.aiMigrationBanner.dismissed'
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000

interface Props {
  /** True when the legacy /api/settings/api-keys endpoint returns rows. */
  hasLegacyKeys: boolean
  onTryNewSetup: () => void
}

export function AIMigrationBanner({ hasLegacyKeys, onTryNewSetup }: Props) {
  const status = useAIProviderStatus()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!hasLegacyKeys) return
    if (status.data?.state === 'connected') return
    if (window.localStorage.getItem(DISMISSED_KEY) === '1') return

    const shownAtRaw = window.localStorage.getItem(SHOWN_AT_KEY)
    const now = Date.now()
    if (shownAtRaw === null) {
      window.localStorage.setItem(SHOWN_AT_KEY, String(now))
      setVisible(true)
      return
    }
    const shownAt = Number(shownAtRaw)
    if (!Number.isFinite(shownAt)) {
      window.localStorage.setItem(SHOWN_AT_KEY, String(now))
      setVisible(true)
      return
    }
    if (now - shownAt > THIRTY_DAYS_MS) {
      setVisible(false)
      return
    }
    setVisible(true)
  }, [hasLegacyKeys, status.data?.state])

  if (!visible) return null

  const dismiss = () => {
    window.localStorage.setItem(DISMISSED_KEY, '1')
    setVisible(false)
  }

  return (
    <div
      role="status"
      data-testid="ai-migration-banner"
      className="flex flex-wrap items-center gap-3 rounded-2xl bg-surface-container px-5 py-3 text-sm text-on-surface"
    >
      <span className="material-symbols-outlined text-primary">auto_awesome</span>
      <p className="flex-1">Try our new one-click AI setup.</p>
      <button
        type="button"
        onClick={dismiss}
        className="rounded-full px-3 py-1.5 text-xs font-medium text-on-surface-variant hover:bg-surface-container-high"
      >
        Not now
      </button>
      <button
        type="button"
        onClick={() => {
          onTryNewSetup()
          dismiss()
        }}
        className="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-on-primary"
      >
        Try it
      </button>
    </div>
  )
}
