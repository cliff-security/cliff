import { useEffect, useRef } from 'react'
import RepoPickerFlow from './RepoPickerFlow'
import type { OnboardingRepoResponse } from '@/api/onboarding'

/**
 * Settings-side dialog that wraps :class:`RepoPickerFlow` so the user
 * can attach a repo to their GitHub App-flow integration without being
 * bounced out to ``/onboarding/connect`` (which would also drag them
 * back through the AI provider step).
 *
 * Keeps the modal chrome consistent with :class:`GithubAppDeviceFlowModal`
 * — same scrim, same surface, same Escape-to-dismiss. CR-1 in PR #145
 * review added: backdrop-click dismissal, ``body`` scroll lock, focus
 * restore to the trigger element on close, and a tiny tab-trap so
 * keyboard navigation cycles inside the modal instead of escaping
 * into the underlying Settings page (which is still in the DOM behind
 * the 30%-opacity scrim).
 */
export function RepoPickerDialog({
  open,
  onClose,
  onConnected,
}: {
  open: boolean
  onClose: () => void
  onConnected: (response: OnboardingRepoResponse) => void
}) {
  const headingRef = useRef<HTMLHeadingElement | null>(null)
  const surfaceRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return undefined

    // Save whoever opened us so we can put focus back when we close.
    triggerRef.current = document.activeElement
    headingRef.current?.focus()

    // Body-scroll lock — prevents the underlying Settings page from
    // scrolling under the modal on trackpad / wheel events.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      // Tiny focus trap: cycle Tab/Shift-Tab inside the surface. Keeps
      // keyboard focus from escaping into the Settings DOM behind the
      // scrim (where it would be invisible but still operable).
      const surface = surfaceRef.current
      if (!surface) return
      const focusable = surface.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      // Best-effort focus restore. ``focus()`` is a no-op for elements
      // that aren't actually focusable any more, which is fine.
      const trigger = triggerRef.current
      if (trigger instanceof HTMLElement) trigger.focus()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="repo-picker-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4"
      data-testid="repo-picker-dialog"
      onMouseDown={(e) => {
        // Backdrop click — dismiss only when the press starts AND ends
        // on the scrim itself (not when the user dragged a selection
        // out from inside the surface).
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={surfaceRef}
        className="w-full max-w-lg rounded-2xl bg-surface-container-lowest p-6 shadow-xl shadow-slate-300/40"
        // Stop click bubbling so a click on whitespace inside the
        // surface doesn't trip the backdrop dismissal above.
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-surface-container-low flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-primary">
              folder_open
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <h3
              id="repo-picker-dialog-title"
              ref={headingRef}
              tabIndex={-1}
              className="text-lg font-semibold tracking-tight text-on-surface focus:outline-none"
            >
              Pick a repository
            </h3>
            <p className="text-sm text-on-surface-variant mt-1">
              Choose the repo OpenSec should secure. We'll clone it and run
              an assessment right after.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-on-surface-variant hover:text-on-surface rounded-md transition-colors"
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-xl">close</span>
          </button>
        </div>

        <RepoPickerFlow caption="" onConnected={onConnected} />
      </div>
    </div>
  )
}
