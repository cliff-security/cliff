/**
 * IssueSeverityBadge — Cliff Cyberdeck severity chip for the Issues page.
 *
 * Tactical mono uppercase label (CRIT/HIGH/MED/LOW) inside a hairline chip
 * tinted by severity:
 *   critical → rose (with glow), high → amber, medium → cyan, low → fg-3
 *
 * Posture-category findings render as a cyan posture chip with the
 * matching Material Symbol.
 */
import type { ReactElement, CSSProperties } from 'react'

export type IssueSeverityKind = 'critical' | 'high' | 'medium' | 'low'

export type IssuePostureCategory =
  | 'repo_configuration'
  | 'code_integrity'
  | 'ci_supply_chain'
  | 'collaborator_hygiene'

interface IssueSeverityBadgeProps {
  kind: IssueSeverityKind
  size?: 'sm' | 'md'
}

interface IssuePostureBadgeProps {
  category?: IssuePostureCategory | string | null
  size?: 'sm' | 'md'
}

interface SeverityVisual {
  label: string
  shortLabel: string
  icon: string
  chip: string
}

const SEVERITY_VISUALS: Record<IssueSeverityKind, SeverityVisual> = {
  critical: { label: 'Critical', shortLabel: 'Critical', icon: 'crisis_alert', chip: 'cd-chip cd-chip--red' },
  high:     { label: 'High',     shortLabel: 'High',     icon: 'warning',      chip: 'cd-chip cd-chip--amber' },
  medium:   { label: 'Medium',   shortLabel: 'Medium',   icon: 'error',        chip: 'cd-chip cd-chip--cyan' },
  low:      { label: 'Low',      shortLabel: 'Low',      icon: 'info',         chip: 'cd-chip cd-chip--ink' },
}

const POSTURE_VISUALS: Record<string, { label: string; icon: string }> = {
  repo_configuration: { label: 'Repo config', icon: 'tune' },
  code_integrity: { label: 'Code integrity', icon: 'verified' },
  ci_supply_chain: { label: 'CI/CD', icon: 'precision_manufacturing' },
  collaborator_hygiene: { label: 'Access', icon: 'group' },
}

function sizeStyle(size: 'sm' | 'md'): CSSProperties {
  return size === 'sm'
    ? { padding: '2px 7px', fontSize: 9.5 }
    : { padding: '3px 9px', fontSize: 10 }
}

export function IssuePostureBadge({
  category,
  size = 'md',
}: IssuePostureBadgeProps): ReactElement {
  const visual = category != null ? POSTURE_VISUALS[category] : undefined
  const v = visual ?? { label: 'Posture', icon: 'verified_user' }
  const iconSize = size === 'sm' ? 12 : 13

  return (
    <span
      className="cd-chip cd-chip--cyan"
      style={sizeStyle(size)}
      aria-label={`Posture · ${v.label}`}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: iconSize, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
        aria-hidden="true"
      >
        {v.icon}
      </span>
      {v.label}
    </span>
  )
}

export function IssueSeverityBadge({
  kind,
  size = 'md',
}: IssueSeverityBadgeProps): ReactElement {
  const v = SEVERITY_VISUALS[kind]
  const iconSize = size === 'sm' ? 12 : 13

  return (
    <span
      className={v.chip}
      style={sizeStyle(size)}
      aria-label={`Severity ${v.label}`}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: iconSize, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
        aria-hidden="true"
      >
        {v.icon}
      </span>
      {v.shortLabel}
    </span>
  )
}
