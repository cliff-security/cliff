/**
 * IssueDeltaChip — signed-percent change pill with directional icon.
 *
 * ``lowerIsBetter=true`` means a negative delta is the good direction
 * (fewer open issues, faster time-to-close). The chip flips tone
 * accordingly: tertiary-container (positive direction) or muted-error
 * (negative direction).
 */
export default function IssueDeltaChip({
  pct,
  lowerIsBetter = true,
}: {
  pct: number
  lowerIsBetter?: boolean
}) {
  const positive = lowerIsBetter ? pct < 0 : pct > 0
  const tone = positive
    ? { bg: 'var(--tertiary-container, #d2d9f8)', fg: 'var(--on-tertiary-container, #444c65)' }
    : { bg: 'rgba(158, 63, 78, 0.10)', fg: 'var(--on-error-container, #782232)' }
  const icon = pct < 0 ? 'trending_down' : 'trending_up'

  return (
    <span
      data-testid="issue-delta-chip"
      className="inline-flex items-center gap-1 font-semibold rounded-full"
      style={{
        background: tone.bg,
        color: tone.fg,
        padding: '2px 7px',
        fontSize: 11,
        lineHeight: 1.1,
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: 12 }}
        aria-hidden
      >
        {icon}
      </span>
      <span className="font-mono">
        {Math.abs(pct)}% · 30d
      </span>
    </span>
  )
}
