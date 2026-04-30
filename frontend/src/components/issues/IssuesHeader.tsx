/**
 * IssuesHeader — Phase 1 (PRD-0006) component.
 *
 * Title row: "Issues" (32px Manrope ExtraBold) + caption with the live counts
 * derived client-side from the findings list:
 *
 *   {open} open · {closed_last_7_days} closed in the last 7 days · grade {grade}
 *
 * `grade` is read from the existing useDashboard hook by the parent page; the
 * component itself is purely presentational so it stays test-friendly.
 *
 * Filter chips: Type and Severity. Phase 1 hard-codes Type to [All,
 * Vulnerability] (the All option is the no-op default; Vulnerability is the
 * only populated value while we ship vulnerability-only). Severity narrows
 * the list via the `onSeverityFilterChange` callback.
 */
import { useMemo, useState, type ReactElement } from 'react'
import type { Finding } from '../../api/client'
import { IssueFilterChip } from './IssueFilterChip'

export type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low'

interface IssuesHeaderProps {
  findings: Finding[]
  grade: string | null | undefined
  severityFilter: SeverityFilter
  onSeverityFilterChange: (filter: SeverityFilter) => void
}

const SEVERITY_LABELS: Array<{ key: Exclude<SeverityFilter, 'all'>; label: string }> = [
  { key: 'critical', label: 'Critical' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
]

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000

export function IssuesHeader({
  findings,
  grade,
  severityFilter,
  onSeverityFilterChange,
}: IssuesHeaderProps): ReactElement {
  // ``Date.now()`` is captured once at mount via ``useState`` initializer.
  // The closed-last-7-days count is a presentational hint — staleness on
  // long-lived sessions (>7 days open) is acceptable for Phase 1, and the
  // ``useState`` initializer keeps the component compatible with the
  // ``react-hooks/purity`` rule (no impure calls during render).
  const [mountedAt] = useState(() => Date.now())
  const sevenDaysAgo = mountedAt - SEVEN_DAYS_MS
  const counts = useMemo(() => {
    let open = 0
    let closedLast7 = 0
    const bySev: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 }
    for (const f of findings) {
      const section = f.derived?.section
      if (section === 'review' || section === 'in_progress' || section === 'todo') {
        open += 1
      } else if (section === 'done') {
        const ts = Date.parse(f.updated_at)
        if (Number.isFinite(ts) && ts >= sevenDaysAgo) {
          closedLast7 += 1
        }
      }
      const sev = (f.raw_severity ?? 'medium').toLowerCase()
      if (sev in bySev) bySev[sev] += 1
    }
    return { open, closedLast7, bySev }
  }, [findings, sevenDaysAgo])

  const total = findings.length

  return (
    <header className="px-8 pt-7 pb-1">
      <div className="flex items-end gap-4 mb-3">
        <h1
          className="font-headline font-extrabold text-on-surface"
          style={{
            fontSize: 32,
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
          }}
        >
          Issues
        </h1>
      </div>
      <p
        data-testid="issues-caption"
        className="text-[12.5px] text-on-surface-variant mb-4"
      >
        <span>{counts.open} open</span>
        <span className="mx-1.5 text-outline">·</span>
        <span>{counts.closedLast7} closed in the last 7 days</span>
        <span className="mx-1.5 text-outline">·</span>
        <span>{grade ? `grade ${grade}` : 'pre-assessment'}</span>
      </p>

      {/* Type filter — display chips. Filtering wires up post-Phase-1; for
          now both Vulnerability and Posture are surfaced when present so the
          catch-all label is "All issues". */}
      <div className="flex items-center gap-2 mb-2" role="group" aria-label="Type filter">
        <span className="text-[10.5px] uppercase tracking-wider font-bold text-on-surface-variant pr-1">
          Type
        </span>
        <IssueFilterChip active count={total}>
          All issues
        </IssueFilterChip>
        <IssueFilterChip icon="bug_report">Vulnerability</IssueFilterChip>
        <IssueFilterChip icon="verified_user">Posture</IssueFilterChip>
      </div>

      {/* Severity filter — drives the visible row set. */}
      <div
        className="flex items-center gap-2"
        role="group"
        aria-label="Severity filter"
      >
        <span className="text-[10.5px] uppercase tracking-wider font-bold text-on-surface-variant pr-1">
          Severity
        </span>
        <IssueFilterChip
          active={severityFilter === 'all'}
          count={total}
          onClick={() => onSeverityFilterChange('all')}
        >
          All severities
        </IssueFilterChip>
        {SEVERITY_LABELS.map(({ key, label }) => (
          <IssueFilterChip
            key={key}
            active={severityFilter === key}
            count={counts.bySev[key]}
            onClick={() => onSeverityFilterChange(key)}
          >
            {label}
          </IssueFilterChip>
        ))}
      </div>
    </header>
  )
}
