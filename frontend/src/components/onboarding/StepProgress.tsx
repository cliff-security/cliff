import type { CSSProperties } from 'react'

export interface StepProgressProps {
  /** 1-indexed current step. */
  current: 1 | 2 | 3
  /** Right-side hint row — defaults to the three step labels. */
  summary?: string
}

/**
 * Three-segment progress bar for the onboarding wizard — Cyberdeck dress.
 *
 * Hairline track with sage fill for completed/current segments; the
 * "Step N of 3" label uses the mono tactical pattern matching the rest
 * of the system.
 */
export default function StepProgress({
  current,
  summary = 'Connect · AI · Assess',
}: StepProgressProps) {
  return (
    <div style={{ marginBottom: 36 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 10,
        }}
        aria-hidden="true"
      >
        {[1, 2, 3].map((n) => {
          const filled = n <= current
          const style: CSSProperties = {
            flex: 1,
            height: 2,
            background: filled ? 'var(--cd-green)' : 'var(--cd-rule)',
            boxShadow: filled ? '0 0 8px var(--cd-green-glow)' : 'none',
            transition: 'background 180ms, box-shadow 180ms',
          }
          return <div key={n} style={style} />
        })}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontFamily: 'var(--cd-mono)',
          fontSize: 10.5,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          fontWeight: 700,
        }}
        role="status"
        aria-label={`Step ${current} of 3`}
      >
        <span style={{ color: 'var(--cd-green)', textShadow: '0 0 6px var(--cd-green-glow)' }}>
          Step {current} of 3
        </span>
        <span style={{ color: 'var(--cd-fg-4)' }}>{summary}</span>
      </div>
    </div>
  )
}
