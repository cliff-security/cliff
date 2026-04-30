/**
 * IssueSeverityBadge — Phase 1 (PRD-0006) atom for the Issues page.
 *
 * Mirrors the IPSeverity prototype in
 * `frontend/mockups/claude-design/PRD-0006/issues-page/atoms.jsx` 1:1 using
 * existing Tailwind / Stitch tokens (no raw hex). Severity is encoded
 * redundantly: color + icon + label, per the design system's accessibility
 * rule.
 *
 * Coexists with the legacy `SeverityBadge` (uppercase pill); this is the new
 * pill-with-icon variant that the IssueRow grid expects.
 */
import type { ReactElement } from 'react'

export type IssueSeverityKind = 'critical' | 'high' | 'medium' | 'low'

/** Posture findings have no CVSS-style severity; we render a category-aware
 *  pill instead so users can tell "this is a config/CI hygiene check"
 *  apart from "this is a CVE in a dependency". */
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
  icon: string
  /** Tailwind class blob — token-based, no raw hex. */
  classes: string
}

const SEVERITY_VISUALS: Record<IssueSeverityKind, SeverityVisual> = {
  critical: {
    label: 'Critical',
    icon: 'crisis_alert',
    classes: 'bg-error/12 text-on-error-container',
  },
  high: {
    // ADR-0029 warning family — closest token match for the prototype's
    // amber-on-cream high severity.
    label: 'High',
    icon: 'warning',
    classes: 'bg-warning-container/50 text-warning-dim',
  },
  medium: {
    label: 'Medium',
    icon: 'error',
    classes: 'bg-secondary-container text-on-secondary-container',
  },
  low: {
    label: 'Low',
    icon: 'info',
    classes: 'bg-tertiary-container text-on-tertiary-container',
  },
}

const POSTURE_VISUALS: Record<string, { label: string; icon: string }> = {
  repo_configuration: { label: 'Repo config', icon: 'tune' },
  code_integrity: { label: 'Code integrity', icon: 'verified' },
  ci_supply_chain: { label: 'CI/CD', icon: 'precision_manufacturing' },
  collaborator_hygiene: { label: 'Access', icon: 'group' },
}

export function IssuePostureBadge({
  category,
  size = 'md',
}: IssuePostureBadgeProps): ReactElement {
  const visual = category != null ? POSTURE_VISUALS[category] : undefined
  const v = visual ?? { label: 'Posture', icon: 'verified_user' }
  const padY = size === 'sm' ? 2 : 3
  const padX = size === 'sm' ? 7 : 9
  const fontSize = size === 'sm' ? '10.5px' : '11px'
  const iconSize = size === 'sm' ? 12 : 13

  return (
    <span
      className="inline-flex items-center gap-1 font-semibold rounded-full bg-surface-container-high text-on-surface-variant"
      style={{
        padding: `${padY}px ${padX}px`,
        fontSize,
        lineHeight: 1,
        letterSpacing: '0.005em',
      }}
      aria-label={`Posture · ${v.label}`}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: iconSize, fontVariationSettings: "'FILL' 1" }}
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
  const padY = size === 'sm' ? 2 : 3
  const padX = size === 'sm' ? 7 : 9
  const fontSize = size === 'sm' ? '10.5px' : '11px'
  const iconSize = size === 'sm' ? 12 : 13

  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold rounded-full ${v.classes}`}
      style={{
        padding: `${padY}px ${padX}px`,
        fontSize,
        lineHeight: 1,
        letterSpacing: '0.005em',
      }}
      aria-label={`Severity ${v.label}`}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: iconSize, fontVariationSettings: "'FILL' 1" }}
        aria-hidden="true"
      >
        {v.icon}
      </span>
      {v.label}
    </span>
  )
}
