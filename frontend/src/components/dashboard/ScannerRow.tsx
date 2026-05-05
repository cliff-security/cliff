/**
 * ScannerRow — one row in the LastAssessmentPanel's scanner list
 * (IMPL-0009 / F7).
 *
 * Generic over the AssessmentTool shape so the future Secret-Sweeper split
 * (CEO follow-up) is data-only with no component refactor needed.
 */
import { formatDurationMs } from './durationFormat'

export type ScannerRowData = {
  id: string
  label: string
  version?: string | null
  icon?: string | null
  ran?: string | null
  scope?: string | null
  duration_ms?: number | null
  result?: {
    kind: 'findings_count' | 'pass_count'
    value: number
    text: string
  } | null
}

export default function ScannerRow({ tool }: { tool: ScannerRowData }) {
  const findings = tool.result?.kind === 'findings_count' ? tool.result.value : null
  const pass = tool.result?.kind === 'pass_count' ? tool.result.value : null

  return (
    <li
      data-testid={`scanner-row-${tool.id}`}
      className="flex items-center gap-4 py-3"
      style={{
        borderBottom: '1px solid var(--outline-variant, #abb3b7)',
        opacity: 1,
      }}
    >
      {/* Identity (220px fixed) */}
      <div className="flex items-center gap-3" style={{ width: 220, flexShrink: 0 }}>
        <span
          aria-hidden
          className="inline-flex items-center justify-center rounded-lg"
          style={{
            width: 32,
            height: 32,
            background: 'var(--surface-container-high, #e3e9ec)',
            color: 'var(--on-surface, #2b3437)',
            flexShrink: 0,
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 18 }}
          >
            {tool.icon || 'extension'}
          </span>
        </span>
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span
              className="font-semibold truncate"
              style={{ fontSize: 13, color: 'var(--on-surface, #2b3437)' }}
            >
              {tool.label.replace(/\s+\d.*$/, '')}
            </span>
            {tool.version && (
              <span
                className="font-mono"
                style={{
                  fontSize: 10.5,
                  color: 'var(--on-surface-variant, #586064)',
                }}
              >
                v{tool.version}
              </span>
            )}
          </div>
          {tool.ran && (
            <div
              className="truncate"
              style={{
                fontSize: 11,
                color: 'var(--on-surface-variant, #586064)',
              }}
            >
              {tool.ran}
            </div>
          )}
        </div>
      </div>

      {/* Scope */}
      <div
        className="flex-1 min-w-0 truncate"
        style={{
          fontSize: 12,
          color: 'var(--on-surface-variant, #586064)',
          textWrap: 'pretty' as never,
        }}
      >
        {tool.scope ?? ''}
      </div>

      {/* Result cluster */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <span
          className="font-mono"
          style={{
            fontSize: 10.5,
            color: 'var(--on-surface-variant, #586064)',
          }}
        >
          {formatDurationMs(tool.duration_ms)}
        </span>
        <FindingsChip findings={findings} pass={pass} total={tool.result?.text} />
        <DoneDot />
      </div>
    </li>
  )
}

function FindingsChip({
  findings,
  pass,
  total,
}: {
  findings: number | null
  pass: number | null
  total?: string | null
}) {
  if (pass != null) {
    // Posture row — pass count out of total. ``total`` carries free-form
    // text like "12 pass"; we re-derive from the text when possible.
    return (
      <span
        data-testid="scanner-row-pass-chip"
        className="rounded-full font-semibold tabular-nums"
        style={{
          fontSize: 11,
          padding: '2px 8px',
          background: 'var(--tertiary-container, #d2d9f8)',
          color: 'var(--on-tertiary-container, #444c65)',
        }}
      >
        {total ?? `${pass} pass`}
      </span>
    )
  }
  const count = findings ?? 0
  const isClean = count === 0
  return (
    <span
      data-testid="scanner-row-findings-chip"
      className="rounded-full font-semibold tabular-nums"
      style={{
        fontSize: 11,
        padding: '2px 8px',
        background: isClean
          ? 'var(--tertiary-container, #d2d9f8)'
          : 'rgba(158, 63, 78, 0.10)',
        color: isClean
          ? 'var(--on-tertiary-container, #444c65)'
          : 'var(--on-error-container, #782232)',
      }}
    >
      {count} {count === 1 ? 'finding' : 'findings'}
    </span>
  )
}

function DoneDot() {
  return (
    <span
      aria-hidden
      className="inline-flex items-center justify-center rounded-full"
      style={{
        width: 22,
        height: 22,
        background: 'var(--tertiary-container, #d2d9f8)',
        color: 'var(--on-tertiary-container, #444c65)',
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{
          fontSize: 14,
          fontVariationSettings: '"FILL" 1, "wght" 500',
        }}
      >
        check
      </span>
    </span>
  )
}

// formatDurationMs lives in ./durationFormat to satisfy the
// ``react-refresh/only-export-components`` lint rule.
