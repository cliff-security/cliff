/**
 * Severity → CSS-variable colour map. Imported by both the
 * cd-chip-based severity badges and the Dashboard's stacked
 * SeverityBar so the two surfaces never drift apart.
 *
 * Lives in its own module (not co-located with the badge component)
 * so Vite's `react-refresh/only-export-components` rule stays happy.
 */

export type SeverityKind = 'critical' | 'high' | 'medium' | 'low'

export const SEVERITY_COLOR_VAR: Record<SeverityKind, string> = {
  critical: 'var(--cd-red)',
  high: 'var(--cd-amber)',
  medium: 'var(--cd-cyan)',
  low: 'var(--cd-fg-4)',
}
