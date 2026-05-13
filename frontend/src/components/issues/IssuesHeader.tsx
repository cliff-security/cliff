/**
 * IssuesHeader — Cliff Cyberdeck Issues page header.
 *
 * Sticky topbar (mirrors PageShell) + sticky filter sub-bar with the
 * dropdown FilterSelect pattern from `ui-kit/issues.jsx`. Two
 * dropdowns — Type and Severity — and a right-aligned "Showing all N"
 * mono hint.
 *
 * Subtitle is computed live from the findings list:
 *
 *   {open} open · {closed_last_7_days} closed in the last 7 days · grade {grade}
 */
import { useMemo, useState, type ReactElement } from 'react'
import type { Finding } from '../../api/client'
import { IssueFilterSelect, type FilterOption } from './IssueFilterSelect'

export type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low'
export type TypeFilter = 'all' | 'vulnerability' | 'posture' | 'secret' | 'license'

interface IssuesHeaderProps {
  findings: Finding[]
  grade: string | null | undefined
  severityFilter: SeverityFilter
  onSeverityFilterChange: (filter: SeverityFilter) => void
  /** Type filter (vulnerability / posture / secret / license). Optional
   *  so existing callers and unit tests that don't care about the type
   *  dimension still type-check. */
  typeFilter?: TypeFilter
  onTypeFilterChange?: (filter: TypeFilter) => void
}

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000

const SEVERITY_DOT: Record<Exclude<SeverityFilter, 'all'>, string> = {
  critical: 'var(--cd-red)',
  high: 'var(--cd-amber)',
  medium: 'var(--cd-cyan)',
  low: 'var(--cd-fg-4)',
}

export function IssuesHeader({
  findings,
  grade,
  severityFilter,
  onSeverityFilterChange,
  typeFilter = 'all',
  onTypeFilterChange,
}: IssuesHeaderProps): ReactElement {
  const [mountedAt] = useState(() => Date.now())
  const sevenDaysAgo = mountedAt - SEVEN_DAYS_MS

  const counts = useMemo(() => {
    let open = 0
    let closedLast7 = 0
    const bySev: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 }
    const byType: Record<string, number> = {
      vulnerability: 0,
      posture: 0,
      secret: 0,
      license: 0,
    }
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

      const t = (f.type ?? 'vulnerability').toLowerCase()
      // CVE-shaped findings live under several internal type names
      // (`dependency`, `code`); roll them up under "vulnerability" for
      // the filter dropdown which is what the user thinks of them as.
      const typeKey =
        t === 'posture' || t === 'secret' || t === 'license'
          ? t
          : 'vulnerability'
      byType[typeKey] += 1
    }
    return { open, closedLast7, bySev, byType }
  }, [findings, sevenDaysAgo])

  const total = findings.length

  const subtitle = useMemo(
    () =>
      `${counts.open} open · ${counts.closedLast7} closed in the last 7 days · ${
        grade ? `grade ${grade}` : 'pre-assessment'
      }`,
    [counts.open, counts.closedLast7, grade],
  )

  // Type filter — display-only for Phase 1 (no callback), parked at "all".
  const typeOptions: FilterOption[] = [
    { id: 'all', label: 'All', count: total },
    { id: 'vulnerability', label: 'Vulnerability', count: counts.byType.vulnerability },
    { id: 'posture', label: 'Posture', count: counts.byType.posture },
    { id: 'secret', label: 'Secret', count: counts.byType.secret },
    { id: 'license', label: 'License', count: counts.byType.license },
  ]

  const sevOptions: FilterOption[] = [
    { id: 'all', label: 'All', count: total },
    { id: 'critical', label: 'Crit', count: counts.bySev.critical, dot: SEVERITY_DOT.critical },
    { id: 'high', label: 'High', count: counts.bySev.high, dot: SEVERITY_DOT.high },
    { id: 'medium', label: 'Med', count: counts.bySev.medium, dot: SEVERITY_DOT.medium },
    { id: 'low', label: 'Low', count: counts.bySev.low, dot: SEVERITY_DOT.low },
  ]

  const filtered = severityFilter !== 'all' || typeFilter !== 'all'
  // The "X of Y" hint counts items visible under the *active* filters.
  // We approximate by intersecting the two filter dimensions; exact rows
  // post-filter live downstream in `useMemo` on the page.
  let visibleCount = total
  if (typeFilter !== 'all') visibleCount = counts.byType[typeFilter] ?? 0
  if (severityFilter !== 'all') {
    // When both are active we conservatively report the smaller bucket;
    // the canonical filtered list is the rendered rows below.
    visibleCount = Math.min(visibleCount, counts.bySev[severityFilter] ?? 0)
  }

  return (
    <>
      {/* Themed topbar — mirrors PageShell. */}
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 20,
          padding: '14px 28px',
          borderBottom: '1px solid var(--cd-rule)',
          background: 'var(--cd-bg-1)',
          display: 'flex',
          alignItems: 'center',
          gap: 18,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 14,
              flexWrap: 'wrap',
              minWidth: 0,
            }}
          >
            <h1
              className="font-display font-extrabold"
              style={{
                fontSize: 32,
                letterSpacing: '-0.025em',
                lineHeight: 1,
                color: 'var(--cd-fg-1)',
                margin: 0,
              }}
            >
              Issues
            </h1>
            <span
              data-testid="issues-caption"
              style={{ fontSize: 14, color: 'var(--cd-fg-3)' }}
            >
              {subtitle}
            </span>
          </div>
        </div>
      </header>

      {/* Sticky filter sub-bar — dropdowns + right-aligned count hint. */}
      <div
        style={{
          position: 'sticky',
          top: 64,
          zIndex: 19,
          background: 'var(--cd-bg-2)',
          borderBottom: '1px solid var(--cd-rule)',
          padding: '14px 28px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
        }}
      >
        <IssueFilterSelect
          label="Type"
          value={typeFilter}
          options={typeOptions}
          onChange={(id) => onTypeFilterChange?.(id as TypeFilter)}
        />
        <IssueFilterSelect
          label="Severity"
          value={severityFilter}
          options={sevOptions}
          onChange={(id) => onSeverityFilterChange(id as SeverityFilter)}
        />
        <span
          style={{
            marginLeft: 'auto',
            fontSize: 13,
            color: 'var(--cd-fg-3)',
          }}
        >
          {filtered ? `Filtered · ${visibleCount} of ${total}` : `Showing all ${total}`}
        </span>
      </div>
    </>
  )
}
