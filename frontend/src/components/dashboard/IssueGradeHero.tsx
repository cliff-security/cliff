/**
 * IssueGradeHero — 192px Manrope ExtraBold grade letter in a primary-
 * container card with a label, caption, and two CTAs (Open Review queue,
 * View grading rubric).
 *
 * Mirrors ``IPGradeHero`` from the PRD-0006 design handoff. ``letter`` is
 * a single capital A-F or null (pre-first-assessment). null renders as an
 * em dash with reduced opacity so the layout is stable.
 */
import type { ReactNode } from 'react'

export type GradeLetter = 'A' | 'B' | 'C' | 'D' | 'F'

export default function IssueGradeHero({
  letter,
  label,
  caption,
  onOpenReview,
  onViewRubric,
  rightSlot,
}: {
  letter: GradeLetter | null
  label: string
  caption: string
  onOpenReview?: () => void
  onViewRubric?: () => void
  rightSlot?: ReactNode
}) {
  const display = letter ?? '—'
  const letterColor =
    letter === null ? 'var(--on-primary-container, #3f33d6)' : 'var(--primary, #4d44e3)'

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
          className="font-headline font-extrabold leading-none"
          style={{
            fontSize: 192,
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
          className="font-headline font-extrabold leading-tight tracking-tight mb-3"
          style={{ fontSize: 36 }}
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
            <span className="material-symbols-outlined text-sm" aria-hidden>
              rate_review
            </span>
            Open Review queue
          </button>
          <button
            type="button"
            onClick={onViewRubric}
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
    </section>
  )
}
