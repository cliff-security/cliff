/**
 * LevelUpPanel — right card on the redesigned dashboard (IMPL-0009 / F6).
 *
 * Header: a tinted icon block + title ("Level up to {next}") + summary on
 * the left; a pill-arrow-pill grade transition on the right.
 *
 * Body: a list of GateRows (≤4). Footer: the rubric copy + a "View full
 * rubric" link that opens the same dialog the IssueGradeHero uses.
 */
import GateRow, { type GateRowData } from './GateRow'

export type LevelUpPanelData = {
  current: 'A' | 'B' | 'C' | 'D' | 'F'
  next: 'A' | 'B' | 'C' | 'D' | 'F' | null
  summary: string
  gates: GateRowData[]
}

export default function LevelUpPanel({
  data,
  onNavigate,
  onAutoFix,
  onAutoFixError,
  autoFixErrors,
  onViewRubric,
  autoFixPending,
}: {
  data: LevelUpPanelData
  onNavigate?: (href: string) => void
  onAutoFix?: (checkNames: string[]) => Promise<void> | void
  /** Q01R B24 — forwarded from each ``GateRow`` so the parent can record
   * which gate's auto-fix failed and why. */
  onAutoFixError?: (gateId: string, message: string) => void
  /** Q01R B24 — map of gate id -> inline error message to render on its card. */
  autoFixErrors?: Record<string, string | null | undefined>
  onViewRubric?: () => void
  /** Map of gate id -> in-flight flag, for the auto-fix action. */
  autoFixPending?: Record<string, boolean>
}) {
  const nextLetter = data.next ?? data.current

  return (
    <section
      data-testid="level-up-panel"
      className="rounded-2xl border border-outline-variant p-6 flex flex-col gap-4"
      style={{ background: 'var(--surface-container-lowest, #ffffff)' }}
    >
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="inline-flex items-center justify-center rounded-xl"
            style={{
              width: 40,
              height: 40,
              background: 'var(--primary-container, #e2dfff)',
              color: 'var(--primary, #4d44e3)',
            }}
          >
            <span
              className="material-symbols-outlined"
              style={{
                fontSize: 22,
                fontVariationSettings: '"FILL" 1, "wght" 500',
              }}
            >
              trending_up
            </span>
          </span>
          <div>
            <h2
              className="font-headline font-extrabold leading-tight"
              style={{ fontSize: 18 }}
            >
              Level up to{' '}
              <span style={{ color: 'var(--primary, #4d44e3)' }}>
                {nextLetter}
              </span>
            </h2>
            <p
              className="mt-1"
              style={{
                fontSize: 12.5,
                color: 'var(--on-surface-variant, #586064)',
                textWrap: 'pretty' as never,
              }}
            >
              {data.summary}
            </p>
          </div>
        </div>

        <div
          className="flex items-center gap-2"
          aria-label={`Grade transition ${data.current} to ${nextLetter}`}
        >
          <GradePill
            letter={data.current}
            tone="current"
          />
          <span
            aria-hidden
            className="material-symbols-outlined"
            style={{
              fontSize: 18,
              color: 'var(--on-surface-variant, #586064)',
            }}
          >
            arrow_forward
          </span>
          <GradePill letter={nextLetter} tone="next" />
        </div>
      </header>

      {data.gates.length === 0 ? (
        <p
          className="text-[13px]"
          style={{ color: 'var(--on-surface-variant, #586064)' }}
        >
          You're already meeting the bar. Hold the line.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.gates.map((gate) => (
            <GateRow
              key={gate.id}
              gate={gate}
              onNavigate={onNavigate}
              onAutoFix={onAutoFix}
              onAutoFixError={
                onAutoFixError
                  ? (message) => onAutoFixError(gate.id, message)
                  : undefined
              }
              error={autoFixErrors?.[gate.id] ?? null}
              pending={autoFixPending?.[gate.id]}
            />
          ))}
        </ul>
      )}

      <p
        className="mt-2"
        style={{
          fontSize: 11,
          color: 'var(--on-surface-variant, #586064)',
          textWrap: 'pretty' as never,
        }}
      >
        Grading rubric · An <strong>{nextLetter}</strong> requires zero open
        Criticals, ≤ 3 High findings, no committed secrets, and all 15
        posture checks passing.{' '}
        <button
          type="button"
          onClick={onViewRubric}
          className="inline-flex items-center gap-0.5"
          style={{
            color: 'var(--primary, #4d44e3)',
            fontWeight: 600,
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
          }}
        >
          View full rubric
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 11 }}
            aria-hidden
          >
            north_east
          </span>
        </button>
      </p>
    </section>
  )
}

function GradePill({
  letter,
  tone,
}: {
  letter: string
  tone: 'current' | 'next'
}) {
  const styles =
    tone === 'current'
      ? {
          background: 'var(--primary-container, #e2dfff)',
          color: 'var(--primary, #4d44e3)',
        }
      : {
          background: 'var(--surface-container-high, #e3e9ec)',
          color: 'var(--on-surface-variant, #586064)',
        }
  return (
    <span
      data-testid={`level-up-grade-pill-${tone}`}
      className="font-headline font-extrabold rounded-md"
      style={{
        ...styles,
        padding: '4px 10px',
        fontSize: 14,
        lineHeight: 1.1,
      }}
    >
      {letter}
    </span>
  )
}
