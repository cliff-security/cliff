/**
 * IssueGradeHero — Cliff Cyberdeck status hero.
 *
 * Mirrors `ui-kit/dashboard.jsx` ("Am I OK?" card):
 *  - tactical corner-bracket frame
 *  - 100px SVG grade ring with sage arc + glow
 *  - ▸ SECURITY POSTURE mono label
 *  - Manrope 26px headline + 13.5px caption
 *  - cd-btn primary / outline action row
 *
 * The component contract is unchanged (letter, label, caption,
 * onOpenReview, rightSlot) so the dashboard wires through as-is.
 */
import { useRef, type ReactNode } from 'react'

export type GradeLetter = 'A' | 'B' | 'C' | 'D' | 'F'

const RUBRIC_BODY = (
  <>
    <p className="text-[13px] leading-relaxed" style={{ color: 'var(--cd-fg-3)' }}>
      Your repository's grade tracks four guarantees that protect against the
      most common compromises:
    </p>
    <ul
      className="text-[13px] leading-relaxed list-disc pl-5 space-y-1.5"
      style={{ textWrap: 'pretty' as never, color: 'var(--cd-fg-2)' }}
    >
      <li>
        <strong style={{ color: 'var(--cd-fg-1)' }}>No open Critical findings.</strong>{' '}
        Hard gate — one Critical drops you below A.
      </li>
      <li>
        <strong style={{ color: 'var(--cd-fg-1)' }}>≤ 3 High findings.</strong>{' '}
        Compromise gate — a small backlog is acceptable; sustained piles aren't.
      </li>
      <li>
        <strong style={{ color: 'var(--cd-fg-1)' }}>No committed secrets.</strong>{' '}
        Hard gate — secrets in source history must be revoked, then rotated.
      </li>
      <li>
        <strong style={{ color: 'var(--cd-fg-1)' }}>All 15 posture checks passing.</strong>{' '}
        Branch protection, Dependabot, CODEOWNERS, signed commits, secret scanning, etc.
      </li>
    </ul>
    <p className="text-[12px] leading-relaxed" style={{ color: 'var(--cd-fg-4)' }}>
      Bands: A = 10/10 · B = 8–9 · C = 6–7 · D = 4–5 · F = 0–3.
    </p>
  </>
)

/** SVG grade ring — sage arc on a hairline track. Stroke length is mapped
 *  from the letter so the ring fills more for higher grades. */
function GradeRingSVG({ letter }: { letter: GradeLetter | null }) {
  const pct =
    letter === 'A' ? 0.92
    : letter === 'B' ? 0.74
    : letter === 'C' ? 0.55
    : letter === 'D' ? 0.32
    : letter === 'F' ? 0.18
    : 0
  const circumference = 2 * Math.PI * 56
  const targetDash = pct * circumference

  // Stroke-fill animation on mount via the `.cd-stroke-on-mount`
  // utility (defined in cyberdeck.css). The arc length is set as a
  // CSS custom property (`--cd-stroke-length`) and the keyframe sweeps
  // `stroke-dashoffset` from full → 0 over 700ms. Honours
  // prefers-reduced-motion automatically via the @media guard on the
  // utility class.
  const arcLength = targetDash

  return (
    <div style={{ position: 'relative', width: 124, height: 124, flexShrink: 0 }}>
      <svg width="124" height="124" viewBox="0 0 124 124">
        <circle
          cx="62" cy="62" r="56"
          fill="none"
          stroke="var(--cd-rule)"
          strokeWidth="3"
        />
        {letter !== null && (
          <circle
            cx="62" cy="62" r="56"
            fill="none"
            stroke="var(--cd-green)"
            strokeWidth="3"
            strokeDasharray={`${arcLength} ${circumference - arcLength}`}
            strokeLinecap="round"
            transform="rotate(-90 62 62)"
            className="cd-stroke-on-mount"
            style={
              {
                ['--cd-stroke-length']: `${arcLength}`,
                filter: 'drop-shadow(0 0 6px var(--cd-green))',
              } as React.CSSProperties & Record<`--${string}`, string>
            }
          />
        )}
      </svg>
      <div
        data-testid="issue-grade-hero-letter"
        style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'var(--cd-display)',
          fontSize: 56,
          fontWeight: 800,
          letterSpacing: '-0.04em',
          color: letter === null ? 'var(--cd-fg-4)' : 'var(--cd-green)',
          textShadow: letter === null ? 'none' : '0 0 18px var(--cd-green-glow)',
          opacity: letter === null ? 0.7 : 1,
        }}
        aria-hidden
      >
        {letter ?? '—'}
      </div>
    </div>
  )
}

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
  rightSlot?: ReactNode
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)

  const openRubric = () => {
    const dlg = dialogRef.current
    if (!dlg) return
    if (typeof dlg.showModal === 'function') {
      try {
        dlg.showModal()
        return
      } catch {
        // already open in some browsers
      }
    }
    dlg.setAttribute('open', '')
  }
  const closeRubric = () => dialogRef.current?.close()

  return (
    <section data-testid="issue-grade-hero" className="cd-frame">
      <div className="cd-frame-br" />
      {/* Whisper-quiet sage dot-grid layer fades behind the hero,
       * masked to the centre so it never reads as decoration. The
       * gradient sits on top and provides the warm-up tint. */}
      <div
        aria-hidden
        className="cd-grid-bg"
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'relative',
          padding: '30px 32px',
          background: 'linear-gradient(180deg, rgba(111,227,181,0.07), transparent 70%)',
          display: 'grid',
          gridTemplateColumns: rightSlot ? '124px 1fr auto' : '124px 1fr',
          gap: 30,
          alignItems: 'center',
        }}
      >
        <GradeRingSVG letter={letter} />

        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontFamily: 'var(--cd-display)',
              fontSize: 32,
              fontWeight: 800,
              color: 'var(--cd-fg-1)',
              letterSpacing: '-0.025em',
              lineHeight: 1.15,
              marginBottom: 10,
              textWrap: 'pretty' as never,
            }}
          >
            {label}
          </div>
          <p
            style={{
              fontSize: 14,
              color: 'var(--cd-fg-3)',
              lineHeight: 1.55,
              maxWidth: 540,
              marginBottom: 16,
            }}
          >
            {caption}
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {onOpenReview && (
              <button
                type="button"
                onClick={onOpenReview}
                className="cd-btn cd-btn--primary cd-btn--sm"
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontSize: 13, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
                  aria-hidden
                >
                  rate_review
                </span>
                Open review queue
              </button>
            )}
            <button
              type="button"
              onClick={openRubric}
              data-testid="issue-grade-hero-view-rubric"
              className="cd-btn cd-btn--ghost cd-btn--sm"
            >
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 13, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
                aria-hidden
              >
                info
              </span>
              Grading rubric
            </button>
          </div>
        </div>

        {rightSlot && (
          <div style={{ minWidth: 0 }}>{rightSlot}</div>
        )}
      </div>

      <dialog
        ref={dialogRef}
        data-testid="issue-grade-hero-rubric-dialog"
        className="p-0 backdrop:bg-black/60"
        style={{
          maxWidth: 460,
          width: '100%',
          background: 'var(--cd-card)',
          border: '1px solid var(--cd-rule)',
          borderRadius: 2,
          color: 'var(--cd-fg-2)',
        }}
        onClick={(e) => {
          if (e.target === dialogRef.current) closeRubric()
        }}
      >
        <div style={{ padding: '22px 24px' }} className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2
                className="font-display font-extrabold"
                style={{
                  fontSize: 18,
                  letterSpacing: '-0.02em',
                  color: 'var(--cd-fg-1)',
                }}
              >
                How cliff grades a repo
              </h2>
            </div>
            <button
              type="button"
              onClick={closeRubric}
              aria-label="Close"
              style={{ color: 'var(--cd-fg-4)', background: 'transparent', border: 'none', cursor: 'pointer' }}
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
