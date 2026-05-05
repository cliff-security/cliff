/**
 * LevelUpProgressPuck — circular progress indicator for a single Level-up gate
 * (IMPL-0009 / F2).
 *
 * 28×28 outer ring with a `conic-gradient` fill at the gate's progress %, and
 * a 22×22 inner circle. When the gate is met (current ≤ target for hard gates,
 * current ≥ target for posture aggregate), it shows a filled `check` icon;
 * otherwise it shows the remaining count in monospace.
 *
 * The "met" semantic is direction-aware:
 * - Hard gates (target = 0): met when current === 0.
 * - Posture aggregate (target > 0): met when current === target.
 * - Anywhere in between: not met.
 *
 * Reduced-motion: the conic gradient is a static background so there is
 * nothing to suppress. The component renders identically in both modes.
 */

type Props = {
  current: number
  target: number
  /** When true, the puck shows a check icon and a fully-filled ring. */
  met?: boolean
}

export default function LevelUpProgressPuck({ current, target, met }: Props) {
  const isMet = met ?? _gateMet(current, target)
  const pct = Math.max(0, Math.min(100, _gatePct(current, target, isMet)))
  const remaining = isMet ? 0 : Math.max(0, _gateRemaining(current, target))

  return (
    <span
      data-testid="level-up-progress-puck"
      data-met={isMet ? 'true' : 'false'}
      className="inline-flex items-center justify-center flex-shrink-0"
      style={{
        width: 28,
        height: 28,
        borderRadius: '999px',
        background: `conic-gradient(var(--primary, #4d44e3) ${pct}%, var(--surface-container-high, #e3e9ec) ${pct}%)`,
      }}
      aria-hidden
    >
      <span
        className="inline-flex items-center justify-center"
        style={{
          width: 22,
          height: 22,
          borderRadius: '999px',
          background: 'var(--surface-container-low, #f1f4f6)',
        }}
      >
        {isMet ? (
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 14,
              color: 'var(--tertiary, #575e78)',
              fontVariationSettings: '"FILL" 1, "wght" 500',
            }}
          >
            check
          </span>
        ) : (
          <span
            className="font-mono font-bold"
            style={{
              fontSize: 10,
              lineHeight: 1,
              color: 'var(--on-surface, #2b3437)',
            }}
          >
            {remaining}
          </span>
        )}
      </span>
    </span>
  )
}

function _gateMet(current: number, target: number): boolean {
  // Hard gate: target = 0 means "drive current to 0".
  if (target === 0) return current <= 0
  // Aggregate gate: target > 0 means "reach this many passes".
  return current >= target
}

function _gatePct(current: number, target: number, met: boolean): number {
  if (met) return 100
  if (target === 0) {
    // Hard gate progress is the inverse of "open count" — show a small
    // amount of ring filled to indicate work in flight.
    return current > 0 ? 0 : 100
  }
  return Math.round((current / target) * 100)
}

function _gateRemaining(current: number, target: number): number {
  if (target === 0) return current
  return target - current
}
