/**
 * OpenBySeverityCard — left card on the dashboard, demoted per critique.
 *
 * The Grade hero is the page's answer to "Am I OK?". This card is a
 * *detail* — total open count, per-severity breakdown, weekly trend.
 * Visual weight is intentionally lower than the hero: the total now
 * renders as a medium Manrope number with the "OPEN FINDINGS" mono
 * eyebrow on top, not a massive 44px display digit.
 */
import {
  IssueSeverityBadge,
  type IssueSeverityKind,
} from '@/components/issues/IssueSeverityBadge'
import { SEVERITY_COLOR_VAR } from '@/components/issues/severityTokens'
import IssueDeltaChip from './IssueDeltaChip'

type Row = {
  kind: IssueSeverityKind
  count: number
  weekly_delta: number
}

// Severity → CSS variable mapping is owned by IssueSeverityBadge so
// the chip and the stacked bar can't drift apart.
const SEVERITY_FILL = SEVERITY_COLOR_VAR

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
      style={{
        background: 'var(--cd-card)',
        border: '1px solid var(--cd-rule)',
        /* Hero card padding rhythm — matches the Grade hero / Review
         * is-clear card. Critique round 2: pick one of two card
         * padding contracts (hero = 28×32, dense list = 14×16) and
         * stop drifting between them. */
        padding: '28px 32px',
        display: 'flex',
        flexDirection: 'column',
        gap: 18,
        width: 380,
        maxWidth: '100%',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div
            className="cd-section-label cd-section-label--quiet"
            style={{ marginBottom: 6 }}
          >
            Open findings
          </div>
          <div
            className="font-display font-bold tabular-nums"
            style={{
              fontSize: 28,
              lineHeight: 1,
              color: 'var(--cd-fg-1)',
              letterSpacing: '-0.02em',
            }}
          >
            {total}
          </div>
          <div
            style={{
              fontSize: 12,
              color: 'var(--cd-fg-4)',
              marginTop: 4,
            }}
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
        <div style={{ fontSize: 13, color: 'var(--cd-fg-3)', lineHeight: 1.5 }}>
          Nothing open right now. New scans drop their findings here.
        </div>
      )}

      {total > 0 && (
        <ul style={{ display: 'flex', flexDirection: 'column', gap: 4, margin: 0, padding: 0, listStyle: 'none' }}>
          {rows.map((r) => (
            <li key={r.kind}>
              <button
                type="button"
                data-testid={`open-by-severity-row-${r.kind}`}
                onClick={() => onSelectSeverity?.(r.kind)}
                className="cd-row"
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '6px 8px',
                  textAlign: 'left',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                <IssueSeverityBadge kind={r.kind} size="sm" />
                <span style={{ marginLeft: 'auto' }} />
                <span
                  className="font-mono font-semibold tabular-nums"
                  style={{ fontSize: 13, color: 'var(--cd-fg-2)' }}
                >
                  {r.count}
                </span>
                <span
                  className="font-mono tabular-nums"
                  style={{
                    fontSize: 11,
                    color: 'var(--cd-fg-4)',
                    width: 64,
                    textAlign: 'right',
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
      style={{
        display: 'flex',
        /* Cooled per critique round 2: was 6px / 0.9 — too loud
         * relative to the chips beneath that already carry the
         * severity signal. */
        height: 4,
        background: 'var(--cd-bg-2)',
        border: '1px solid var(--cd-rule)',
        overflow: 'hidden',
      }}
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
              opacity: 0.7,
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
