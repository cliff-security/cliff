/**
 * IssueDeltaChip — signed-change pill with directional icon.
 *
 * Cyberdeck colour rules per critique:
 *   - "good direction" (e.g. fewer issues, lower percent) → sage
 *   - "bad direction" (more issues, higher percent) → amber (attention)
 *   - flat / zero → fg-4 neutral
 *
 * Rose is reserved for genuine 9.0+ CVSS criticals — never used here.
 *
 * Two modes:
 *  - `pct` (legacy callers): renders `${|pct|}% · 30d`
 *  - `count` (Open findings card): renders `${sign}${|value|} · ${suffix}`
 *
 * `lowerIsBetter=true` (default) means a negative number is the good
 * direction.
 */

type CommonProps = {
  lowerIsBetter?: boolean
}

type PctProps = CommonProps & {
  mode?: 'pct'
  pct: number
}

type CountProps = CommonProps & {
  mode: 'count'
  value: number
  suffix?: string
}

type Props = PctProps | CountProps

const GOOD = { fg: 'var(--cd-green)', border: 'var(--cd-green-line)' }
const BAD = { fg: 'var(--cd-amber)', border: 'rgba(240, 191, 126, 0.35)' }
const FLAT = { fg: 'var(--cd-fg-4)', border: 'var(--cd-rule)' }

export default function IssueDeltaChip(props: Props) {
  const lowerIsBetter = props.lowerIsBetter ?? true

  if (props.mode === 'count') {
    const { value, suffix = 'wk' } = props
    let tone = FLAT
    let icon = 'remove'
    let label = `— ${suffix}`

    if (value !== 0) {
      const positive = lowerIsBetter ? value < 0 : value > 0
      tone = positive ? GOOD : BAD
      icon = value < 0 ? 'trending_down' : 'trending_up'
      const sign = value > 0 ? '+' : value < 0 ? '−' : ''
      label = `${sign}${Math.abs(value)} · ${suffix}`
    }

    return (
      <span
        data-testid="issue-delta-chip"
        className="font-mono"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          color: tone.fg,
          border: `1px solid ${tone.border}`,
          background: 'transparent',
          padding: '2px 7px',
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: '0.06em',
          borderRadius: 2,
        }}
      >
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 12, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
          aria-hidden
        >
          {icon}
        </span>
        {label}
      </span>
    )
  }

  // ── pct mode (legacy callers) ────────────────────────────────────────────
  const { pct } = props
  const positive = lowerIsBetter ? pct < 0 : pct > 0
  const tone = pct === 0 ? FLAT : positive ? GOOD : BAD
  const icon = pct === 0 ? 'remove' : pct < 0 ? 'trending_down' : 'trending_up'

  return (
    <span
      data-testid="issue-delta-chip"
      className="font-mono"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        color: tone.fg,
        border: `1px solid ${tone.border}`,
        background: 'transparent',
        padding: '2px 7px',
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: '0.06em',
        borderRadius: 2,
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: 12, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
        aria-hidden
      >
        {icon}
      </span>
      {Math.abs(pct)}% · 30d
    </span>
  )
}
