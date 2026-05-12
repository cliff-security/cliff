/**
 * Root modal for AI provider onboarding (IMPL-0011 G3).
 *
 * Thin wrapper around ``AIProviderFlow`` that owns the dialog chrome
 * (overlay, Esc + click-outside dismissal) and remounts the inner flow
 * on each open so picker state can't leak across sessions.
 *
 * Serene Sentinel rules:
 *   - tonal layering, no 1px borders
 *   - sentence case throughout
 *   - Manrope headings (font-headline), Inter body
 *   - primary CTAs use bg-primary text-on-primary
 *   - Material Symbols icons via the `material-symbols-outlined` class
 */

import { useCallback, useEffect } from 'react'
import { AIProviderFlow } from './AIProviderFlow'

interface Props {
  open: boolean
  onClose: () => void
  /** Optional callback fired once the user reaches a connected state. */
  onConnected?: () => void
}

export function AIProviderModal(props: Props) {
  if (!props.open) return null
  return <AIProviderModalInner {...props} />
}

function AIProviderModalInner({ open, onClose, onConnected }: Props) {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const handleConnected = useCallback(() => {
    onConnected?.()
    onClose()
  }, [onConnected, onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI provider setup"
      data-testid="ai-provider-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4 py-10"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-xl rounded-3xl bg-surface p-8 shadow-xl">
        <AIProviderFlow
          enableAutodetect={open}
          onConnected={handleConnected}
          onDismiss={onClose}
        />
      </div>
    </div>
  )
}
