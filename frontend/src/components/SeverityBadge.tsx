/**
 * SeverityBadge — Cliff Cyberdeck tactical severity chip.
 *
 * Mono uppercase, hairline border, severity-tinted ink.
 *   critical → rose (with glow), high → amber, medium → cyan, low → fg-3
 *
 * Mirrors `specimens/colors-severity.html`. Kept the old export surface
 * (size: 'sm' | 'md') for the existing call sites.
 */

type SeverityKey = 'critical' | 'high' | 'medium' | 'low'

const severityConfig: Record<SeverityKey, { label: string; chip: string }> = {
  critical: { label: 'Critical', chip: 'cd-chip cd-chip--red' },
  high:     { label: 'High',     chip: 'cd-chip cd-chip--amber' },
  medium:   { label: 'Medium',   chip: 'cd-chip cd-chip--cyan' },
  low:      { label: 'Low',      chip: 'cd-chip cd-chip--ink' },
}

const SEVERITY_ICONS: Record<SeverityKey, string> = {
  critical: 'crisis_alert',
  high: 'warning',
  medium: 'info',
  low: 'info',
}

interface SeverityBadgeProps {
  severity: string | null | undefined
  size?: 'sm' | 'md'
}

function getKey(severity: string | null | undefined): SeverityKey {
  const k = (severity ?? 'medium').toLowerCase() as SeverityKey
  if (k === 'critical' || k === 'high' || k === 'medium' || k === 'low') return k
  return 'medium'
}

export default function SeverityBadge({ severity, size = 'sm' }: SeverityBadgeProps) {
  const key = getKey(severity)
  const config = severityConfig[key]

  const sizeStyle =
    size === 'md'
      ? { padding: '4px 10px', fontSize: 10 }
      : { padding: '3px 8px', fontSize: 9.5 }

  return (
    <span className={config.chip} style={sizeStyle}>
      {config.label}
    </span>
  )
}

/**
 * SeverityIcon — circular monogram for the issue detail hero. Cyberdeck
 * replaces the soft filled circle with a sage-edged frame containing a
 * stroke-only Material Symbol tinted by severity.
 */
export function SeverityIcon({ severity }: { severity: string | null | undefined }) {
  const key = getKey(severity)
  const config = severityConfig[key]

  const colorMap: Record<SeverityKey, string> = {
    critical: 'var(--cd-red)',
    high: 'var(--cd-amber)',
    medium: 'var(--cd-cyan)',
    low: 'var(--cd-fg-3)',
  }
  const tint = colorMap[key]

  return (
    <div
      className={`w-12 h-12 flex items-center justify-center ${config.chip}`}
      style={{
        borderRadius: '999px',
        padding: 0,
        color: tint,
      }}
    >
      <span
        className="material-symbols-outlined"
        aria-hidden
        style={{ fontSize: 22, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
      >
        {SEVERITY_ICONS[key]}
      </span>
    </div>
  )
}
