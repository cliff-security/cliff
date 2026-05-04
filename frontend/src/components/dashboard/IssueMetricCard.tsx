/**
 * IssueMetricCard — single-metric card with eyebrow + delta chip on the
 * top row, big value + sparkline on the second row, and an optional
 * footnote underneath.
 *
 * Mirrors ``IPMetricCard`` from the PRD-0006 design handoff.
 */
import IssueDeltaChip from './IssueDeltaChip'
import IssueSparkline from './IssueSparkline'

export default function IssueMetricCard({
  label,
  value,
  deltaPct,
  lowerIsBetter = true,
  series,
  footnote,
  accent = 'primary',
}: {
  label: string
  value: string
  deltaPct: number
  lowerIsBetter?: boolean
  series: Array<number | null>
  footnote?: string
  accent?: 'primary' | 'tertiary'
}) {
  const sparklineColor =
    accent === 'tertiary'
      ? 'var(--tertiary, #575e78)'
      : 'var(--primary, #4d44e3)'

  return (
    <section
      data-testid="issue-metric-card"
      className="rounded-2xl p-6 flex flex-col"
      style={{
        background: 'var(--surface-container-lowest, #ffffff)',
        border: '1px solid var(--outline-variant, #abb3b7)',
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11.5px] uppercase tracking-wider text-on-surface-variant font-bold">
          {label}
        </div>
        <IssueDeltaChip pct={deltaPct} lowerIsBetter={lowerIsBetter} />
      </div>
      <div className="flex items-end justify-between gap-4">
        <div
          data-testid="issue-metric-card-value"
          className="font-headline font-extrabold text-on-surface tracking-tight"
          style={{ fontSize: 44, lineHeight: 1 }}
        >
          {value}
        </div>
        <IssueSparkline data={series} width={120} height={36} color={sparklineColor} />
      </div>
      {footnote && (
        <p
          className="text-[12px] text-on-surface-variant mt-3"
          style={{ textWrap: 'pretty' as never }}
        >
          {footnote}
        </p>
      )}
    </section>
  )
}
