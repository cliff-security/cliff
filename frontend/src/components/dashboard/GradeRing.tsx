/**
 * GradeRing — hero conic-gradient ring showing the security grade.
 *
 * IMPL-0002 Milestone G3. The filled arc reflects criteria met / total; the
 * letter at the center shows the grade (A–F) or an em-dash while the
 * assessment is still running.
 */

export interface GradeRingProps {
  grade: 'A' | 'B' | 'C' | 'D' | 'F' | null
  criteriaMet: number
  criteriaTotal: number
}

export default function GradeRing({
  grade,
  criteriaMet,
  criteriaTotal,
}: GradeRingProps) {
  const safeTotal = Math.max(criteriaTotal, 1)
  const pct = Math.min(1, Math.max(0, criteriaMet / safeTotal))
  const degrees = Math.round(pct * 360)

  const ringStyle = {
    background: `conic-gradient(var(--cd-green, #6FE3B5) 0 ${degrees}deg, var(--cd-card-hov, #161E32) ${degrees}deg 360deg)`,
    boxShadow: '0 0 24px rgba(111,227,181,0.15)',
  } as const

  return (
    <div
      data-testid="grade-ring"
      className="relative grid h-[180px] w-[180px] place-items-center rounded-full"
      style={ringStyle}
      role="img"
      aria-label={`Security grade ${grade ?? 'pending'}, ${criteriaMet} of ${criteriaTotal} criteria met`}
    >
      <div className="grid h-[146px] w-[146px] place-items-center rounded-full bg-surface">
        <span
          data-testid="grade-letter"
          className="font-headline text-6xl font-bold leading-none text-on-surface"
        >
          {grade ?? '—'}
        </span>
        <span className="mt-1 text-xs font-medium text-on-surface-variant">
          {criteriaMet} of {criteriaTotal}
        </span>
      </div>
    </div>
  )
}
