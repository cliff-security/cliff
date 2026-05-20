/**
 * ScannerRow — one row in the LastAssessmentPanel's scanner list
 * (IMPL-0009 / F7).
 *
 * Generic over the AssessmentTool shape so the future Secret-Sweeper split
 * (CEO follow-up) is data-only with no component refactor needed.
 *
 * B07 — the row is state-aware: a ``skipped`` scanner (timed out, binary
 * missing, exec failure) renders a distinct warning indicator and a chip
 * that names the reason, so it never reads as a clean "0 findings" run.
 */
import { formatDurationMs } from './durationFormat'

type ToolState = 'pending' | 'active' | 'done' | 'skipped'
type ToolError = 'timeout' | 'binary_missing' | 'exec_failed'

export type ScannerRowData = {
  id: string
  label: string
  state: ToolState
  version?: string | null
  icon?: string | null
  ran?: string | null
  scope?: string | null
  duration_ms?: number | null
  error?: ToolError | null
  result?: {
    kind: 'findings_count' | 'pass_count'
    value: number
    text: string
  } | null
}

const SKIPPED_REASON: Record<ToolError, string> = {
  timeout: 'timed out',
  binary_missing: 'unavailable',
  exec_failed: 'scan failed',
}

const SKIPPED_TITLE: Record<ToolError, string> = {
  timeout:
    'This scanner timed out before it finished — its results are not in the grade. Larger repos may need a longer budget; see Configure scanners.',
  binary_missing:
    'This scanner binary was unavailable, so it did not run. See Configure scanners.',
  exec_failed:
    'This scanner failed to run, so its results are not in the grade. See Configure scanners.',
}

export default function ScannerRow({ tool }: { tool: ScannerRowData }) {
  const findings = tool.result?.kind === 'findings_count' ? tool.result.value : null
  const pass = tool.result?.kind === 'pass_count' ? tool.result.value : null
  const skipped = tool.state === 'skipped'

  return (
    <li
      data-testid={`scanner-row-${tool.id}`}
      data-state={tool.state}
      className="flex items-center gap-4 py-3"
      style={{
        borderBottom: '1px solid var(--outline-variant, #abb3b7)',
        opacity: skipped ? 0.85 : 1,
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
        {skipped ? (
          <>
            <SkippedChip error={tool.error ?? null} />
            <SkippedDot error={tool.error ?? null} />
          </>
        ) : (
          <>
            <FindingsChip findings={findings} pass={pass} total={tool.result?.text} />
            <DoneDot />
          </>
        )}
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

function SkippedChip({ error }: { error: ToolError | null }) {
  const reason = error ? SKIPPED_REASON[error] : 'skipped'
  return (
    <span
      data-testid="scanner-row-skipped-chip"
      className="rounded-full font-semibold"
      style={{
        fontSize: 11,
        padding: '2px 8px',
        background: 'var(--cd-amber-soft, rgba(240, 191, 126, 0.16))',
        color: 'var(--cd-amber, #f0bf7e)',
      }}
    >
      {reason}
    </span>
  )
}

function DoneDot() {
  return (
    <span
      data-testid="scanner-row-status-done"
      aria-label="Completed"
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
        aria-hidden
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

function SkippedDot({ error }: { error: ToolError | null }) {
  const title = error
    ? SKIPPED_TITLE[error]
    : 'This scanner did not produce results, so they are not in the grade.'
  return (
    <span
      data-testid="scanner-row-status-skipped"
      aria-label="Skipped — no results"
      title={title}
      className="inline-flex items-center justify-center rounded-full"
      style={{
        width: 22,
        height: 22,
        background: 'var(--cd-amber-soft, rgba(240, 191, 126, 0.16))',
        color: 'var(--cd-amber, #f0bf7e)',
      }}
    >
      <span
        className="material-symbols-outlined"
        aria-hidden
        style={{
          fontSize: 14,
          fontVariationSettings: '"FILL" 1, "wght" 500',
        }}
      >
        warning
      </span>
    </span>
  )
}

// formatDurationMs lives in ./durationFormat to satisfy the
// ``react-refresh/only-export-components`` lint rule.
