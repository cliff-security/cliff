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
 * — same scrim, same surface, same Escape-to-dismiss.
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

  useEffect(() => {
    if (!open) return undefined
    headingRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="repo-picker-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 px-4"
      data-testid="repo-picker-dialog"
    >
      <div className="w-full max-w-lg rounded-2xl bg-surface-container-lowest p-6 shadow-xl shadow-slate-300/40">
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

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
