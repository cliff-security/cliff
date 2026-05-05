/**
 * IssueDeltaChip — signed-change pill with directional icon.
 *
 * Two modes:
 *
 * - **`pct` mode (default)** — legacy Phase 2 caller shape. Displays
 *   `${|pct|}% · 30d` with `trending_down` / `trending_up` icon and
 *   tertiary-container / muted-error tone driven by `lowerIsBetter`.
 *
 * - **`count` mode** — IMPL-0009 caller shape used by the new
 *   "Open findings" card. Displays `${sign}${|value|} · ${suffix}` (suffix
 *   defaults to `wk`). Adds a third zero state with the `remove` icon and
 *   neutral tone — "no movement this week" reads honestly instead of as
 *   a regression.
 *
 * `lowerIsBetter=true` (default for both modes) means a negative number is
 * the good direction.
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

const TERTIARY_TONE = {
  bg: 'var(--tertiary-container, #d2d9f8)',
  fg: 'var(--on-tertiary-container, #444c65)',
}
const ERROR_TONE = {
  bg: 'rgba(158, 63, 78, 0.10)',
  fg: 'var(--on-error-container, #782232)',
}
const NEUTRAL_TONE = {
  bg: 'var(--surface-container-high, #e3e9ec)',
  fg: 'var(--on-surface-variant, #586064)',
}

export default function IssueDeltaChip(props: Props) {
  const lowerIsBetter = props.lowerIsBetter ?? true

  if (props.mode === 'count') {
    const { value, suffix = 'wk' } = props
    let tone = NEUTRAL_TONE
    let icon = 'remove'
    let label = `— ${suffix}`

    if (value !== 0) {
      const positive = lowerIsBetter ? value < 0 : value > 0
      tone = positive ? TERTIARY_TONE : ERROR_TONE
      icon = value < 0 ? 'trending_down' : 'trending_up'
      const sign = value > 0 ? '+' : value < 0 ? '−' : ''
      label = `${sign}${Math.abs(value)} · ${suffix}`
    }

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
        <span className="font-mono">{label}</span>
      </span>
    )
  }

  // ── pct mode (legacy / Phase 2 callers) ─────────────────────────────────
  const { pct } = props
  const positive = lowerIsBetter ? pct < 0 : pct > 0
  const tone = positive ? TERTIARY_TONE : ERROR_TONE
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
      <span className="font-mono">{Math.abs(pct)}% · 30d</span>
    </span>
  )
}
