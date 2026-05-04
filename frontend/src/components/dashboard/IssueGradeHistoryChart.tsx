/**
 * IssueGradeHistoryChart — 1080×280 stacked-area severity history chart
 * with a dotted vertical marker at the most-recent grade-letter change.
 *
 * Mirrors ``IPGradeHistoryChart`` from the PRD-0006 design handoff but
 * drives off live ``severity_history`` (60-day arrays per severity) and
 * ``grade_history`` (90 daily snapshots) from the dashboard payload. The
 * promotion marker walks the grade history backwards from today and pins
 * to the last day where the grade changed; if no change, the marker is
 * suppressed.
 *
 * Renders nothing when ``severityHistory`` is null or all-zero.
 */
import type { components } from '@/api/types'
import { findPromotion } from './findPromotion'

type SeverityHistory = components['schemas']['SeverityHistory']
type GradeHistoryPoint = components['schemas']['GradeHistoryPoint']

export default function IssueGradeHistoryChart({
  severityHistory,
  gradeHistory,
}: {
  severityHistory: SeverityHistory | null | undefined
  gradeHistory: GradeHistoryPoint[] | undefined
}) {
  if (!severityHistory) return null
  const sev = severityHistory
  const length = sev.critical?.length ?? 0
  if (length === 0) return null

  const totals = Array.from({ length }, (_, i) =>
    (sev.critical?.[i] ?? 0)
    + (sev.high?.[i] ?? 0)
    + (sev.medium?.[i] ?? 0)
    + (sev.low?.[i] ?? 0),
  )
  const maxTotal = Math.max(...totals)
  if (maxTotal === 0) return null

  const W = 1080
  const H = 280
  const padL = 40
  const padR = 12
  const padT = 12
  const padB = 28
  const innerW = W - padL - padR
  const innerH = H - padT - padB
  const maxY = maxTotal * 1.1
  const x = (i: number) => padL + (i / Math.max(1, length - 1)) * innerW
  const y = (v: number) => padT + innerH - (v / maxY) * innerH

  type Stack = {
    i: number
    crit: number
    high: number
    med: number
    low: number
    total: number
  }
  const stack: Stack[] = Array.from({ length }, (_, i) => {
    const c = sev.critical?.[i] ?? 0
    const h = c + (sev.high?.[i] ?? 0)
    const m = h + (sev.medium?.[i] ?? 0)
    const l = m + (sev.low?.[i] ?? 0)
    return { i, crit: c, high: h, med: m, low: l, total: totals[i] }
  })

  const areaPath = (
    upper: (s: Stack) => number,
  ): string => {
    const top = stack
      .map((s, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(upper(s))}`)
      .join(' ')
    const bottom = stack
      .slice()
      .reverse()
      .map((_s, i) => `L${x(length - 1 - i)},${y(0)}`)
      .join(' ')
    return `${top} ${bottom} Z`
  }

  const colors = {
    crit: 'rgba(158, 63, 78, 0.55)',
    high: 'rgba(199, 128, 52, 0.45)',
    med: 'rgba(89, 94, 120, 0.40)',
    low: 'rgba(87, 94, 120, 0.30)',
  }

  const promotion = findPromotion(gradeHistory, length)

  return (
    <svg
      data-testid="issue-grade-history-chart"
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ display: 'block' }}
      role="img"
      aria-label="Open issues over time, stacked by severity."
    >
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <line
          key={`grid-${t}`}
          x1={padL}
          x2={W - padR}
          y1={padT + innerH * t}
          y2={padT + innerH * t}
          stroke="var(--outline-variant, #abb3b7)"
          strokeWidth={1}
        />
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <text
          key={`label-${t}`}
          x={padL - 6}
          y={padT + innerH * t + 4}
          fontSize={10}
          textAnchor="end"
          fill="var(--on-surface-variant, #586064)"
          fontFamily="JetBrains Mono"
        >
          {Math.round(maxY * (1 - t))}
        </text>
      ))}

      {/* Stacked bands (low → med → high → crit). */}
      <path d={areaPath((s) => s.low)} fill={colors.low} />
      <path d={areaPath((s) => s.med)} fill={colors.med} />
      <path d={areaPath((s) => s.high)} fill={colors.high} opacity={0.85} />
      <path d={areaPath((s) => s.crit)} fill={colors.crit} />

      {/* Total line on top of the stack. */}
      <path
        d={stack
          .map((s, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(s.low)}`)
          .join(' ')}
        fill="none"
        stroke="var(--on-surface, #2b3437)"
        strokeWidth={1.5}
      />

      {/* Promotion marker — dotted vertical line + corner pill. */}
      {promotion && promotion.toLetter !== promotion.fromLetter && (
        <g data-testid="issue-grade-history-promotion">
          <line
            x1={x(promotion.index)}
            x2={x(promotion.index)}
            y1={padT}
            y2={padT + innerH}
            stroke="var(--primary, #4d44e3)"
            strokeWidth={1.5}
            strokeDasharray="3 3"
          />
          <g transform={`translate(${x(promotion.index)}, ${padT - 2})`}>
            <rect x={-44} y={-14} width={88} height={18} rx={9} fill="var(--primary, #4d44e3)" />
            <text
              x={0}
              y={-1}
              textAnchor="middle"
              fontSize={10}
              fontWeight={700}
              fill="var(--on-primary, #faf6ff)"
              fontFamily="Manrope"
            >
              {promotion.fromLetter ?? '?'} → {promotion.toLetter} · {promotion.daysAgo}d ago
            </text>
          </g>
        </g>
      )}

      {/* X axis tick labels. */}
      {[0, 14, 30, 45, length - 1]
        .filter((i) => i >= 0 && i < length)
        .map((i) => (
          <text
            key={`x-${i}`}
            x={x(i)}
            y={H - 8}
            fontSize={10}
            textAnchor="middle"
            fill="var(--on-surface-variant, #586064)"
            fontFamily="JetBrains Mono"
          >
            {i === length - 1 ? 'now' : `${length - i}d`}
          </text>
        ))}
    </svg>
  )
}

