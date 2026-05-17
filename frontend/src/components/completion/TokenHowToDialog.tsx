import { useCallback, useEffect, useRef } from 'react'

export interface TokenHowToDialogProps {
  open: boolean
  onClose: () => void
}

/**
 * "How to create a token" modal (UX frame 1.1a).
 *
 * Walks the user through creating a **fine-grained** personal access token
 * scoped to a single repository with the minimum three permissions Cliff
 * needs: Contents (read/write), Pull requests (read/write), Metadata (read).
 * Fine-grained tokens avoid the Classic PAT's "all private repos on your
 * account" blast radius.
 *
 * Scrim + backdrop blur per the mockup. The modal owns focus while open,
 * Escape closes it, and `prefers-reduced-motion` suppresses the fade-in.
 */
export default function TokenHowToDialog({ open, onClose }: TokenHowToDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const previouslyFocusedRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    queueMicrotask(() => closeButtonRef.current?.focus())

    return () => {
      document.body.style.overflow = prevOverflow
      previouslyFocusedRef.current?.focus?.()
    }
  }, [open])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
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
    },
    [onClose],
  )

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      onKeyDown={handleKeyDown}
    >
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-on-surface/50 backdrop-blur-sm motion-safe:transition-opacity"
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="token-howto-title"
        aria-describedby="token-howto-subtitle"
        className="relative w-full max-w-xl bg-surface-container-lowest rounded-2xl shadow-2xl overflow-hidden motion-safe:animate-in motion-safe:fade-in max-h-[90vh] flex flex-col"
      >
        <div className="flex items-start gap-4 px-7 pt-7 pb-5">
          <div className="w-11 h-11 rounded-xl bg-primary-container/60 flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-primary" aria-hidden="true">
              vpn_key
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <h3
              id="token-howto-title"
              className="font-headline text-xl font-extrabold text-on-surface"
            >
              Create a fine-grained GitHub token
            </h3>
            <p
              id="token-howto-subtitle"
              className="text-sm text-on-surface-variant mt-1"
            >
              Scoped to this one repository with three read/write permissions
              — enough to clone, push a branch, and open a draft pull request.
              Nothing else.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded-lg hover:bg-surface-container-low flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-container-lowest"
          >
            <span className="material-symbols-outlined text-on-surface-variant">
              close
            </span>
          </button>
        </div>

        <ol className="px-7 pb-6 space-y-4 overflow-y-auto">
          <Step n={1}>
            <p className="text-sm text-on-surface leading-relaxed">
              Open the fine-grained token settings.
            </p>
            <a
              href="https://github.com/settings/personal-access-tokens/new"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 mt-1.5 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-container-lowest rounded"
            >
              github.com/settings/personal-access-tokens/new
              <span className="material-symbols-outlined text-sm" aria-hidden="true">
                open_in_new
              </span>
            </a>
          </Step>

          <Step n={2}>
            <p className="text-sm text-on-surface leading-relaxed">
              Give it a name like{' '}
              <span className="font-mono bg-surface-container-low px-1.5 py-0.5 rounded text-xs">
                Cliff · your-project
              </span>{' '}
              and pick an expiration (90 days is a reasonable default).
            </p>
          </Step>

          <Step n={3}>
            <p className="text-sm text-on-surface leading-relaxed mb-2">
              Under <span className="font-semibold">Repository access</span>,
              choose{' '}
              <span className="font-semibold">
                Only select repositories
              </span>{' '}
              and pick the single repo you're going to assess.
            </p>
            <p className="text-xs text-on-surface-variant">
              Never grant "All repositories" — Cliff only needs this one.
            </p>
          </Step>

          <Step n={4}>
            <p className="text-sm text-on-surface leading-relaxed mb-2">
              Under <span className="font-semibold">Repository permissions</span>
              , set exactly these three and leave everything else as
              "No access":
            </p>
            <div className="rounded-lg bg-surface-container-low px-4 py-3 space-y-3">
              <PermissionRow
                name="Contents"
                value="Read and write"
                rationale="Clone the repo, create a branch, commit and push fixes."
              />
              <PermissionRow
                name="Pull requests"
                value="Read and write"
                rationale="Open a draft pull request for the fix via gh pr create."
              />
              <PermissionRow
                name="Metadata"
                value="Read-only"
                rationale="Auto-enabled by GitHub when any other permission is set."
                auto
              />
            </div>
            <p className="text-xs text-on-surface-variant mt-2">
              Leave <span className="font-semibold">Account permissions</span>{' '}
              and every other section untouched — Cliff never reads user
              profile data.
            </p>
          </Step>

          <Step n={5}>
            <p className="text-sm text-on-surface leading-relaxed">
              Click <span className="font-semibold">Generate token</span>,
              copy the value starting with{' '}
              <span className="font-mono">github_pat_</span>, and paste it
              back into Cliff.
            </p>
          </Step>
        </ol>

        <div className="px-7 py-4 bg-surface-container-low flex items-start gap-3">
          <span
            className="material-symbols-outlined text-tertiary text-sm mt-0.5"
            aria-hidden="true"
          >
            lock
          </span>
          <p className="text-xs text-on-surface-variant leading-relaxed">
            Tokens are stored locally in your Cliff vault. They never leave
            this machine and are never logged. Revoke any time at{' '}
            <a
              href="https://github.com/settings/personal-access-tokens"
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-primary hover:underline"
            >
              github.com/settings/personal-access-tokens
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  )
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-4">
      <span
        className="w-7 h-7 rounded-full bg-primary text-white font-bold text-sm flex items-center justify-center flex-shrink-0"
        aria-hidden="true"
      >
        {n}
      </span>
      <div className="flex-1 min-w-0">{children}</div>
    </li>
  )
}

function PermissionRow({
  name,
  value,
  rationale,
  auto = false,
}: {
  name: string
  value: string
  rationale: string
  auto?: boolean
}) {
  return (
    <div className="flex items-start gap-3">
      <span
        className="material-symbols-outlined text-tertiary mt-0.5"
        style={{ fontVariationSettings: "'FILL' 1" }}
        aria-hidden="true"
      >
        check_box
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-sm font-semibold text-on-surface">
          {name}{' '}
          <span className="text-primary font-semibold">· {value}</span>
          {auto && (
            <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant align-middle">
              auto
            </span>
          )}
        </p>
        <p className="text-xs text-on-surface-variant mt-0.5">{rationale}</p>
      </div>
    </div>
  )
}
