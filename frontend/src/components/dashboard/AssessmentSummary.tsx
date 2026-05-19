/**
 * AssessmentSummary — Surface 3 interstitial card
 * (PRD-0003 v0.2 / surfaces/assessment-complete.jsx variation A).
 *
 * Shown once after the first assessment completes, gated server-side by
 * ``assessment.summary_seen_at``. Three summary cards (vulns / posture /
 * quick wins) + a grade preview row + a primary "View your report card"
 * CTA that fires :class:`useMarkSummarySeen` and falls through to the
 * report card on the next render.
 */

import GradeRing from './GradeRing'

export type Grade = 'A' | 'B' | 'C' | 'D' | 'F'

export interface AssessmentSummaryStats {
  vulnerabilitiesTotal: number
  postureFailing: number
  posturePassing: number
  postureTotal: number
  quickWins: number
}

export interface AssessmentSummaryProps {
  grade: Grade
  criteriaMet: number
  criteriaTotal: number
  stats: AssessmentSummaryStats
  onViewReportCard: () => void
  pending?: boolean
}

const cx = (...xs: (string | false | null | undefined)[]) =>
  xs.filter(Boolean).join(' ')

export default function AssessmentSummary({
  grade,
  criteriaMet,
  criteriaTotal,
  stats,
  onViewReportCard,
  pending = false,
}: AssessmentSummaryProps) {
  return (
    <section
      data-testid="assessment-summary"
      className="flex flex-col items-center gap-7 rounded-3xl bg-surface-container-low px-8 py-10"
    >
      <header className="flex flex-col items-center gap-2 text-center">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
          Assessment complete
        </p>
        <h1 className="font-headline text-3xl font-extrabold text-on-surface">
          Here&rsquo;s where you stand
        </h1>
      </header>

      <div className="grid w-full max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard
          icon="bug_report"
          label="Vulnerabilities"
          value={stats.vulnerabilitiesTotal}
          subtitle="From scanners · excludes posture checks"
          tone="primary"
        />
        <SummaryCard
          icon="rule"
          label="Posture"
          value={stats.postureFailing}
          subtitle={`Failing — ${stats.posturePassing} of ${stats.postureTotal} pass`}
          tone={stats.postureFailing === 0 ? 'tertiary' : 'warning'}
        />
        <SummaryCard
          icon="bolt"
          label="Quick wins"
          value={stats.quickWins}
          subtitle="Auto-fix candidates"
          tone="primary"
        />
      </div>

      <div
        data-testid="assessment-summary-grade-preview"
        className="flex items-center gap-4"
      >
        <GradeRing
          grade={grade}
          criteriaMet={criteriaMet}
          criteriaTotal={criteriaTotal}
        />
        <div>
          <p className="font-headline text-xl font-bold text-on-surface">
            Grade {grade}
          </p>
          <p className="text-sm text-on-surface-variant tabular-nums">
            {criteriaMet} of {criteriaTotal} criteria met
          </p>
        </div>
      </div>

      <button
        type="button"
        data-testid="assessment-summary-cta"
        onClick={onViewReportCard}
        disabled={pending}
        className={cx(
          'inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-semibold text-on-primary shadow-sm transition active:scale-[0.97]',
          'hover:bg-primary-dim disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
        )}
      >
        <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>
          arrow_forward
        </span>
        View your report card
      </button>
    </section>
  )
}

type SummaryTone = 'primary' | 'tertiary' | 'warning'

function SummaryCard({
  icon,
  label,
  value,
  subtitle,
  tone,
}: {
  icon: string
  label: string
  value: number
  subtitle?: string
  tone: SummaryTone
}) {
  const palette: Record<SummaryTone, { ring: string; text: string }> = {
    primary: {
      ring: 'bg-primary-container/55',
      text: 'text-on-primary-container',
    },
    tertiary: {
      ring: 'bg-tertiary-container/55',
      text: 'text-on-tertiary-container',
    },
    warning: {
      ring: 'bg-warning-container/40',
      text: 'text-on-warning-container',
    },
  }
  const p = palette[tone]
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl bg-surface-container-lowest p-5 text-center">
      <span
        className={cx(
          'flex h-10 w-10 items-center justify-center rounded-xl',
          p.ring,
        )}
      >
        <span
          className={cx('material-symbols-outlined', p.text)}
          style={{ fontSize: 20 }}
          aria-hidden
        >
          {icon}
        </span>
      </span>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant">
        {label}
      </p>
      <p className="font-headline text-3xl font-extrabold tabular-nums text-on-surface">
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-on-surface-variant">{subtitle}</p>
      )}
    </div>
  )
}
