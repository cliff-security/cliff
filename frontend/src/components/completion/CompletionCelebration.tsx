/**
 * CompletionCelebration — the "you did it" overlay.
 *
 * Design notes:
 *  - `role="status" aria-live="assertive"` announces completion to screen
 *    readers on mount. This is an announcement region, NOT a dialog. We
 *    deliberately do not trap focus or respond to Escape — the subordinate
 *    actions below serve as the dismissal path.
 *  - Action hierarchy (UX Rev 4): one filled primary button (Download) +
 *    two text-link subordinates (Copy text / Copy markdown).
 *  - Confetti is owned by `ConfettiLayer`, which self-suppresses under
 *    `prefers-reduced-motion`. The backdrop still renders.
 *
 * Wiring:
 *  - Download scrolls the user to `SummaryActionPanel` AND triggers the
 *    PNG export; the parent provides both behaviors via `onDownloadClick`.
 *  - Copy handlers do clipboard writes + fire-and-forget share-action POSTs
 *    through `useShareAction`; again, wired by the parent.
 */
import ShieldSVG from './ShieldSVG'
import ConfettiLayer from './ConfettiLayer'

export interface CompletionCelebrationProps {
  repoName: string
  /** Formatted date shown verbatim in the body copy and shield caption. */
  completedDate: string
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  /** How many criteria exist — always shown as "{n} of {n} criteria met". */
  criteriaCount: number
  onDownloadClick: () => void
  onCopyTextClick: () => void
  onCopyMarkdownClick: () => void
}

export default function CompletionCelebration({
  repoName,
  completedDate,
  grade,
  criteriaCount,
  onDownloadClick,
  onCopyTextClick,
  onCopyMarkdownClick,
}: CompletionCelebrationProps) {
  return (
    <div
      role="status"
      aria-live="assertive"
      className="relative overflow-hidden bg-gradient-to-br from-tertiary-fixed via-surface to-primary-container/40 px-8 py-16"
      style={{ minHeight: '620px' }}
    >
      <ConfettiLayer />
      <div className="relative mx-auto max-w-xl text-center">
        <span className="text-xs font-bold uppercase tracking-[0.22em] text-primary">
          Grade {grade} · {criteriaCount} of {criteriaCount} criteria met
        </span>
        <h3 className="font-headline text-5xl font-extrabold text-on-surface mt-4 mb-2">
          Security complete
        </h3>
        <p className="text-on-surface-variant text-lg mb-8 max-w-md mx-auto">
          You've reached baseline security on{' '}
          <span className="font-semibold text-on-surface">{repoName}</span>. Completed
          on {completedDate}. Your shareable summary is ready below — keep it
          private or post it, your call.
        </p>

        <div className="flex justify-center">
          <ShieldSVG
            completedDate={completedDate}
            width={150}
            height={180}
          />
        </div>

        <div className="mt-10 flex flex-col items-center gap-4">
          <button
            type="button"
            onClick={onDownloadClick}
            className="px-8 py-3.5 rounded-lg bg-primary text-white font-bold text-sm hover:bg-primary-dim transition-colors active:scale-95 shadow-md flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">download</span>
            Download summary image
          </button>
          <div className="flex items-center gap-6 text-sm">
            <button
              type="button"
              onClick={onCopyTextClick}
              className="font-semibold text-primary hover:text-primary-dim hover:underline transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-sm">
                content_copy
              </span>
              Copy text summary
            </button>
            <span
              aria-hidden="true"
              className="w-px h-4 bg-outline-variant/30"
            />
            <button
              type="button"
              onClick={onCopyMarkdownClick}
              className="font-semibold text-primary hover:text-primary-dim hover:underline transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-sm">code</span>
              Copy markdown
            </button>
          </div>
        </div>

        <p className="mt-6 text-xs text-on-surface-variant max-w-md mx-auto">
          Cliff never writes to your README. The full summary panel with
          previews is just below.
        </p>
      </div>
    </div>
  )
}
