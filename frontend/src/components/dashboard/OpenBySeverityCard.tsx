/**
 * OpenBySeverityCard — left card on the redesigned dashboard
 * (IMPL-0009 / F5). Replaces Phase 2's "Open issues" sparkline metric.
 *
 * Top: total open count + "across N severities" caption + a count-mode
 * IssueDeltaChip summing the weekly deltas. Middle: stacked severity bar
 * with four colored segments. Bottom: per-severity rows with badge + count
 * + delta.
 *
 * Click on a row or a segment navigates to ``/issues?severity=<kind>``.
 */
import {
  IssueSeverityBadge,
  type IssueSeverityKind,
} from '@/components/issues/IssueSeverityBadge'
import IssueDeltaChip from './IssueDeltaChip'

type Row = {
  kind: IssueSeverityKind
  count: number
  weekly_delta: number
}

const SEVERITY_FILL: Record<IssueSeverityKind, string> = {
  critical: 'var(--error, #9e3f4e)',
  high: 'rgb(199,128,52)',
  medium: 'var(--secondary, #595e78)',
  low: 'var(--tertiary, #575e78)',
}

export default function OpenBySeverityCard({
  rows,
  onSelectSeverity,
}: {
  rows: Row[]
  onSelectSeverity?: (kind: IssueSeverityKind) => void
}) {
  const total = rows.reduce((acc, r) => acc + r.count, 0)
  const sumDelta = rows.reduce((acc, r) => acc + r.weekly_delta, 0)
  const presentCount = rows.filter((r) => r.count > 0).length

  return (
    <section
      data-testid="open-by-severity-card"
      className="rounded-2xl bg-surface-container-lowest border border-outline-variant p-6 flex flex-col gap-4"
      style={{ width: 380, maxWidth: '100%' }}
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <div
            className="text-[11.5px] font-bold uppercase tracking-wider"
            style={{ color: 'var(--on-surface-variant, #586064)' }}
          >
            Open findings
          </div>
          <div
            className="font-headline font-extrabold tabular-nums mt-1"
            style={{ fontSize: 44, lineHeight: 1 }}
          >
            {total}
          </div>
          <div
            className="text-[12px] mt-0.5"
            style={{ color: 'var(--on-surface-variant, #586064)' }}
          >
            {total === 0
              ? 'Caught up'
              : `across ${presentCount} ${presentCount === 1 ? 'severity' : 'severities'}`}
          </div>
        </div>
        {total > 0 && <IssueDeltaChip mode="count" value={sumDelta} />}
      </header>

      {total > 0 ? (
        <SeverityBar
          rows={rows}
          total={total}
          onSelect={onSelectSeverity}
        />
      ) : (
        <div
          className="text-[13px]"
          style={{ color: 'var(--on-surface-variant, #586064)' }}
        >
          Nothing open right now. New scans drop their findings here.
        </div>
      )}

      {total > 0 && (
        <ul className="flex flex-col" style={{ gap: 6 }}>
          {rows.map((r) => (
            <li key={r.kind}>
              <button
                type="button"
                data-testid={`open-by-severity-row-${r.kind}`}
                onClick={() => onSelectSeverity?.(r.kind)}
                className="w-full flex items-center gap-3 hover:bg-surface-container-low rounded-md px-1 py-1 -mx-1 text-left"
              >
                <IssueSeverityBadge kind={r.kind} size="sm" />
                <span className="ml-auto" />
                <span
                  className="font-mono font-semibold tabular-nums"
                  style={{
                    fontSize: 13,
                    color: 'var(--on-surface, #2b3437)',
                  }}
                >
                  {r.count}
                </span>
                <span
                  className="font-mono tabular-nums text-right"
                  style={{
                    fontSize: 11,
                    color: 'var(--on-surface-variant, #586064)',
                    width: 64,
                  }}
                >
                  {r.weekly_delta === 0
                    ? '— wk'
                    : `${r.weekly_delta > 0 ? '+' : '−'}${Math.abs(r.weekly_delta)} · wk`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function SeverityBar({
  rows,
  total,
  onSelect,
}: {
  rows: Row[]
  total: number
  onSelect?: (kind: IssueSeverityKind) => void
}) {
  return (
    <div
      data-testid="severity-bar"
      className="flex h-3 rounded-full overflow-hidden"
      role="img"
      aria-label="Open findings by severity"
    >
      {rows.map((r) => {
        if (r.count === 0) return null
        const pct = (r.count / total) * 100
        return (
          <button
            key={r.kind}
            type="button"
            data-testid={`severity-bar-${r.kind}`}
            onClick={() => onSelect?.(r.kind)}
            title={`${r.count} ${r.kind}`}
            style={{
              width: `${pct}%`,
              background: SEVERITY_FILL[r.kind],
              opacity: 0.85,
              border: 'none',
              padding: 0,
              cursor: onSelect ? 'pointer' : 'default',
            }}
            aria-label={`${r.count} ${r.kind}`}
          />
        )
      })}
    </div>
  )
}
