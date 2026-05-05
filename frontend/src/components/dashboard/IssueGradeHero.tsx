/**
 * IssueGradeHero — primary-container card with a 168px Manrope ExtraBold
 * grade letter, eyebrow + label + caption, and two CTAs (Open Review queue,
 * View grading rubric).
 *
 * Mirrors ``IPGradeHero`` from the PRD-0006 design handoff (IMPL-0009).
 * ``letter`` is a single capital A-F or null (pre-first-assessment); null
 * renders as an em dash with reduced opacity so the layout is stable.
 *
 * "View grading rubric" opens a native ``<dialog>`` with the rubric copy.
 * Esc and click-outside close it via standard ``<dialog>`` semantics.
 */
import { useRef, type ReactNode } from 'react'

export type GradeLetter = 'A' | 'B' | 'C' | 'D' | 'F'

const RUBRIC_BODY = (
  <>
    <p className="text-[13px] leading-relaxed">
      Your repository's grade tracks four guarantees that protect against the
      most common compromises:
    </p>
    <ul
      className="text-[13px] leading-relaxed list-disc pl-5 space-y-1.5"
      style={{ textWrap: 'pretty' as never }}
    >
      <li>
        <strong>No open Critical findings.</strong> Hard gate — one Critical
        drops you below A.
      </li>
      <li>
        <strong>≤ 3 High findings.</strong> Compromise gate — a small backlog
        is acceptable; sustained piles aren't.
      </li>
      <li>
        <strong>No committed secrets.</strong> Hard gate — secrets in source
        history must be revoked, then rotated.
      </li>
      <li>
        <strong>All 15 posture checks passing.</strong> Branch protection,
        Dependabot, CODEOWNERS, signed commits, secret scanning, etc.
      </li>
    </ul>
    <p className="text-[12px] leading-relaxed text-on-surface-variant">
      Bands: A = 10/10 · B = 8–9 · C = 6–7 · D = 4–5 · F = 0–3.
    </p>
  </>
)

export default function IssueGradeHero({
  letter,
  label,
  caption,
  onOpenReview,
  rightSlot,
}: {
  letter: GradeLetter | null
  label: string
  caption: string
  onOpenReview?: () => void
  /** Optional slot for additional content on the right. */
  rightSlot?: ReactNode
}) {
  const display = letter ?? '—'
  const letterColor =
    letter === null
      ? 'var(--on-primary-container, #3f33d6)'
      : 'var(--primary, #4d44e3)'
  const dialogRef = useRef<HTMLDialogElement | null>(null)

  const openRubric = () => {
    const dlg = dialogRef.current
    if (!dlg) return
    // jsdom does not implement HTMLDialogElement.showModal — fall back to
    // ``open`` so tests can exercise the toggle path without throwing.
    if (typeof dlg.showModal === 'function') {
      try {
        dlg.showModal()
        return
      } catch {
        // some browsers throw when called twice; fall through to ``open``.
      }
    }
    dlg.setAttribute('open', '')
  }
  const closeRubric = () => dialogRef.current?.close()

  return (
    <section
      data-testid="issue-grade-hero"
      className="rounded-3xl p-8 flex items-center gap-8 flex-wrap"
      style={{
        background: 'var(--primary-container, #e2dfff)',
        color: 'var(--on-primary-container, #3f33d6)',
      }}
    >
      <div className="flex-shrink-0 relative">
        <div
          data-testid="issue-grade-hero-letter"
          className="font-headline font-extrabold"
          style={{
            fontSize: 168,
            color: letterColor,
            letterSpacing: '-0.04em',
            lineHeight: 0.85,
            opacity: letter === null ? 0.45 : 1,
          }}
          aria-hidden
        >
          {display}
        </div>
        <div className="absolute -bottom-2 left-0 text-[11px] font-mono uppercase tracking-wider font-semibold opacity-80">
          A → F · higher is better
        </div>
      </div>

      <div className="flex-1 min-w-[260px]">
        <div className="text-[10.5px] uppercase tracking-wider font-bold mb-1.5 opacity-80">
          Repository grade
        </div>
        <h1
          className="font-headline font-extrabold leading-tight tracking-tight mb-2.5"
          style={{ fontSize: 32 }}
        >
          {label}
        </h1>
        <p
          className="text-[14px] leading-relaxed max-w-xl mb-4"
          style={{ textWrap: 'pretty' as never }}
        >
          {caption}
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={onOpenReview}
            className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold shadow-sm hover:opacity-90"
            style={{
              background: 'var(--primary, #4d44e3)',
              color: 'var(--on-primary, #faf6ff)',
            }}
          >
            <span
              className="material-symbols-outlined text-sm"
              style={{ fontVariationSettings: '"FILL" 1, "wght" 500' }}
              aria-hidden
            >
              rate_review
            </span>
            Open Review queue
          </button>
          <button
            type="button"
            onClick={openRubric}
            data-testid="issue-grade-hero-view-rubric"
            className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold border border-outline-variant bg-surface-container-lowest text-on-surface hover:bg-surface-container"
          >
            View grading rubric
          </button>
        </div>
      </div>

      {rightSlot && (
        <div className="w-full md:w-auto md:max-w-xs md:flex-shrink-0">
          {rightSlot}
        </div>
      )}

      {/* Native dialog — Esc + form-method=dialog close cleanly without a
          third-party modal library. */}
      <dialog
        ref={dialogRef}
        data-testid="issue-grade-hero-rubric-dialog"
        className="rounded-2xl p-0 backdrop:bg-black/40 max-w-md w-full"
        onClick={(e) => {
          // click-outside dismiss
          if (e.target === dialogRef.current) closeRubric()
        }}
      >
        <div className="bg-surface-container-lowest p-6 space-y-3">
          <div className="flex items-start justify-between gap-4">
            <h2 className="font-headline font-extrabold text-[18px] leading-tight">
              Grading rubric
            </h2>
            <button
              type="button"
              onClick={closeRubric}
              aria-label="Close"
              className="text-on-surface-variant hover:text-on-surface"
            >
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 20 }}
                aria-hidden
              >
                close
              </span>
            </button>
          </div>
          {RUBRIC_BODY}
        </div>
      </dialog>
    </section>
  )
}
