/**
 * ShareReportPanel — the badge / completion-progress dialog (B11, PRD-0002
 * Story 5).
 *
 * The "Share report" action on the dashboard opens this. PRD-0002 Story 5
 * requires that *before* completion the user still sees "a preview of the
 * celebration and the remaining criteria — motivating, not discouraging."
 * At grade A the on-dashboard CompletionCelebration block is the emotional
 * peak; this panel then just confirms the badge is earned and points at it.
 */
import { useEffect, useRef } from 'react'
import type { GradeLetter } from './IssueGradeHero'

export type ShareReportCriterion = {
  key: string
  label: string
  met: boolean
}

export default function ShareReportPanel({
  open,
  onClose,
  grade,
  repoName,
  criteria,
}: {
  open: boolean
  onClose: () => void
  grade: GradeLetter | null
  repoName: string
  criteria: ShareReportCriterion[]
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)

  // Upgrade to a true modal in real browsers; the `open` attribute alone
  // keeps the panel visible (and testable) where showModal is unavailable.
  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    if (open && typeof dlg.showModal === 'function' && !dlg.open) {
      try {
        dlg.showModal()
      } catch {
        dlg.setAttribute('open', '')
      }
    } else if (!open && dlg.open) {
      dlg.close()
    }
  }, [open])

  const metCount = criteria.filter((c) => c.met).length
  const total = criteria.length
  const remaining = total - metCount
  const earned = grade === 'A'

  return (
    <dialog
      ref={dialogRef}
      open={open}
      data-testid="share-report-panel"
      className="p-0 backdrop:bg-black/60"
      style={{
        maxWidth: 420,
        width: '100%',
        background: 'var(--cd-card)',
        border: '1px solid var(--cd-rule)',
        borderRadius: 2,
        color: 'var(--cd-fg-2)',
      }}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose()
      }}
      onClose={onClose}
    >
      <div style={{ padding: '24px 26px' }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="cd-section-label cd-section-label--quiet">
              Security report
            </div>
            <h2
              className="font-display"
              style={{ fontSize: 18, color: 'var(--cd-fg-0, #e8edf6)' }}
            >
              {repoName}
            </h2>
          </div>
          <button
            type="button"
            data-testid="share-report-close"
            onClick={onClose}
            className="cd-btn cd-btn--ghost cd-btn--sm"
            aria-label="Close"
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 16 }}
              aria-hidden
            >
              close
            </span>
          </button>
        </div>

        <p
          className="font-mono"
          style={{
            marginTop: 14,
            fontSize: 12,
            color: 'var(--cd-fg-1, #9baccc)',
          }}
        >
          {metCount} of {total} criteria met
        </p>

        <ul style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {criteria.map((c) => (
            <li
              key={c.key}
              data-testid={`share-report-criterion-${c.key}`}
              data-met={c.met ? 'true' : 'false'}
              className="flex items-center gap-2"
              style={{ padding: '6px 0', fontSize: 13 }}
            >
              <span
                className="material-symbols-outlined"
                aria-hidden
                style={{
                  fontSize: 17,
                  color: c.met
                    ? 'var(--cd-green, #6fe3b5)'
                    : 'var(--cd-fg-2, #6b7890)',
                }}
              >
                {c.met ? 'check_circle' : 'radio_button_unchecked'}
              </span>
              <span
                style={{
                  color: c.met
                    ? 'var(--cd-fg-0, #e8edf6)'
                    : 'var(--cd-fg-1, #9baccc)',
                }}
              >
                {c.label}
              </span>
            </li>
          ))}
        </ul>

        {earned ? (
          <p
            data-testid="share-report-earned-line"
            style={{
              marginTop: 16,
              fontSize: 13,
              color: 'var(--cd-fg-1, #9baccc)',
            }}
          >
            You've earned the Cliff badge — the shareable summary card is on
            your dashboard, just below the grade.
          </p>
        ) : (
          <p
            data-testid="share-report-preview-line"
            style={{
              marginTop: 16,
              fontSize: 13,
              color: 'var(--cd-fg-1, #9baccc)',
            }}
          >
            Close the remaining {remaining}{' '}
            {remaining === 1 ? 'criterion' : 'criteria'} to earn your
            shareable Cliff badge. Each one is a step — you don't have to do
            them all at once.
          </p>
        )}
      </div>
    </dialog>
  )
}
