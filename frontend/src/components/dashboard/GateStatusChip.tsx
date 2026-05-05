/**
 * GateStatusChip — tiny status badge for a Level-up gate (IMPL-0009 / F3).
 *
 * Four variants per the design handoff. Tone palette mirrors the prototype's
 * `IPGateRow` chip: ready/pr_ready land on the primary tone (drawing the eye
 * to the most-actionable gates), in_progress on primary-container (ongoing),
 * auto_fixable on tertiary-container (signals "click to do it for you").
 */

export type GateStatus =
  | 'ready_to_review'
  | 'pr_ready'
  | 'in_progress'
  | 'auto_fixable'
  | 'todo'

const VARIANTS: Record<
  GateStatus,
  { label: string; bg: string; fg: string }
> = {
  ready_to_review: {
    label: 'Ready',
    bg: 'var(--primary, #4d44e3)',
    fg: 'var(--on-primary, #faf6ff)',
  },
  pr_ready: {
    label: 'PR ready',
    bg: 'var(--primary, #4d44e3)',
    fg: 'var(--on-primary, #faf6ff)',
  },
  in_progress: {
    label: 'In progress',
    bg: 'var(--primary-container, #e2dfff)',
    fg: 'var(--on-primary-container, #3f33d6)',
  },
  auto_fixable: {
    label: 'Auto-fixable',
    bg: 'var(--tertiary-container, #d2d9f8)',
    fg: 'var(--on-tertiary-container, #444c65)',
  },
  todo: {
    label: 'Start',
    bg: 'var(--surface-container-high, #e3e9ec)',
    fg: 'var(--on-surface-variant, #586064)',
  },
}

export default function GateStatusChip({
  status,
  className,
}: {
  status: GateStatus
  className?: string
}) {
  const v = VARIANTS[status]
  return (
    <span
      data-testid="gate-status-chip"
      data-status={status}
      className={`inline-flex items-center rounded-full font-semibold ${className ?? ''}`}
      style={{
        background: v.bg,
        color: v.fg,
        padding: '2px 7px',
        fontSize: 10,
        lineHeight: 1.1,
        letterSpacing: '0.1px',
      }}
    >
      {v.label}
    </span>
  )
}
