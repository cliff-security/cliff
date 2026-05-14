/**
 * Cliff-branded loading indicator — the neon glyph dot from the wordmark,
 * orbited by a thin arc that rotates. Used wherever an agent is "thinking".
 *
 * Visual: a #6FE3B5 dot with a faint glow at the center, ringed by a partial
 * circular stroke that spins. Reads as "Cliff is working" without dominating
 * the surface it sits on.
 */

interface CliffSpinnerProps {
  /** Outer size in pixels. Defaults to 18 (matches material-symbol fontSize). */
  size?: number
  /** Optional aria-label for screen readers. */
  label?: string
  className?: string
}

export function CliffSpinner({
  size = 18,
  label = 'Working',
  className,
}: CliffSpinnerProps) {
  const center = size / 2
  const ringR = size * 0.42
  const dotR = size * 0.13
  return (
    <span
      role="img"
      aria-label={label}
      className={className}
      style={{ display: 'inline-flex', width: size, height: size }}
    >
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        aria-hidden
      >
        <defs>
          <filter id="cliff-dot-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation={size * 0.06} result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g style={{ transformOrigin: '50% 50%', animation: 'cliff-spin 1.6s linear infinite' }}>
          <circle
            cx={center}
            cy={center}
            r={ringR}
            fill="none"
            stroke="#6FE3B5"
            strokeWidth={size * 0.08}
            strokeLinecap="round"
            strokeDasharray={`${ringR * 1.4} ${ringR * 5}`}
            opacity={0.85}
          />
        </g>
        <circle
          cx={center}
          cy={center}
          r={dotR}
          fill="#6FE3B5"
          filter="url(#cliff-dot-glow)"
        />
      </svg>
      <style>{`
        @keyframes cliff-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @media (prefers-reduced-motion: reduce) {
          [aria-label='${label}'] g { animation: none !important; }
        }
      `}</style>
    </span>
  )
}
