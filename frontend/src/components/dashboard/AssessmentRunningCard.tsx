/**
 * AssessmentRunningCard — the live "scan in flight" surface for the
 * redesigned dashboard (IMPL-0009 / F9).
 *
 * Hero strip (spinner + repo + elapsed time + step counter), overall
 * progress hairline, "POWERED BY" scanner credit pills with active-state
 * pulse-dot, three-state step list, sandbox footer.
 *
 * The component is "polled-from-outside": pass it the AssessmentStatusResponse
 * straight from ``useAssessmentStatus``. Elapsed ticks 1Hz client-side from
 * ``startedAt``.
 */
import { useEffect, useState } from 'react'

type ScannerToolLike = {
  id: string
  label: string
  icon?: string | null
  state?: 'pending' | 'active' | 'done' | 'skipped'
  result?: { kind: string; value: number; text: string } | null
}

type StepLike = {
  key: string
  label: string
  state: string
  progress_pct?: number | null
  detail?: string | null
  result_summary?: string | null
  hint?: string | null
}

export type AssessmentRunningCardProps = {
  repoUrl: string | null
  startedAt?: string | null
  /** 0..100 overall progress. */
  progressPct: number
  /** All steps, in order, with their state. */
  steps: StepLike[]
  tools: ScannerToolLike[]
  /** Optional handlers for the footer ghost buttons (Phase 4+). */
  onViewLiveLog?: () => void
  onConfigureScanners?: () => void
}

export default function AssessmentRunningCard({
  repoUrl,
  startedAt,
  progressPct,
  steps,
  tools,
  onViewLiveLog,
  onConfigureScanners,
}: AssessmentRunningCardProps) {
  const repoName = humanizeRepo(repoUrl)
  const elapsed = useElapsedSeconds(startedAt)
  const stepCounter = computeStepCounter(steps)

  return (
    <section
      data-testid="assessment-running-card"
      className="rounded-3xl border border-outline-variant overflow-hidden"
      style={{ background: 'var(--surface-container-lowest, #ffffff)' }}
      role="status"
      aria-live="polite"
      aria-label="Assessment in progress"
    >
      {/* Hero strip */}
      <div className="flex items-start gap-5 px-8 pt-7 pb-6">
        <div
          aria-hidden
          className="rounded-2xl flex items-center justify-center flex-shrink-0"
          style={{
            width: 56,
            height: 56,
            background: 'var(--primary-container, #e2dfff)',
          }}
        >
          <span
            className="opensec-spinner"
            style={{ width: 22, height: 22 }}
          />
        </div>

        <div className="flex-1 min-w-0">
          <div
            className="text-[10.5px] font-bold uppercase tracking-wider"
            style={{ color: 'var(--primary, #4d44e3)' }}
          >
            Assessing repository
          </div>
          <h2
            className="font-headline font-extrabold leading-tight tracking-tight mt-1"
            style={{ fontSize: 26 }}
          >
            Scanning <span className="font-mono">{repoName}</span>…
          </h2>
          <p
            className="mt-1.5"
            style={{
              fontSize: 13.5,
              color: 'var(--on-surface-variant, #586064)',
              maxWidth: '36rem',
              textWrap: 'pretty' as never,
            }}
          >
            Usually 4–8 minutes. You can leave this page — progress is saved
            on the server and the dashboard flips to your report card the
            moment the scan finishes.
          </p>
        </div>

        <div className="text-right flex-shrink-0">
          <div
            className="text-[10.5px] font-bold uppercase tracking-wider"
            style={{ color: 'var(--on-surface-variant, #586064)' }}
          >
            Elapsed
          </div>
          <div
            data-testid="assessment-running-elapsed"
            className="font-headline font-extrabold tabular-nums"
            style={{ fontSize: 20 }}
          >
            {formatElapsed(elapsed)}
          </div>
          <div
            className="tabular-nums"
            style={{
              fontSize: 11,
              color: 'var(--on-surface-variant, #586064)',
            }}
          >
            {stepCounter}
          </div>
        </div>
      </div>

      {/* Overall progress hairline */}
      <div
        className="mx-8 mb-5 h-1 rounded-full overflow-hidden"
        style={{ background: 'var(--surface-container-high, #e3e9ec)' }}
      >
        <div
          data-testid="assessment-running-overall-bar"
          className="h-full"
          style={{
            width: `${Math.max(0, Math.min(100, progressPct))}%`,
            background: 'var(--primary, #4d44e3)',
            transition: 'width 200ms cubic-bezier(.2, 0, 0, 1)',
          }}
        />
      </div>

      {/* Scanner credit row */}
      <div className="flex items-center justify-between gap-4 px-8 pb-5 flex-wrap">
        <div
          className="text-[10.5px] font-bold uppercase tracking-wider"
          style={{ color: 'var(--on-surface-variant, #586064)' }}
        >
          Powered by
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {tools.map((tool) => (
            <ScannerPill key={tool.id} tool={tool} />
          ))}
        </div>
      </div>

      {/* Step list */}
      <ul className="px-3 pb-3 list-none" role="list">
        {steps.map((step) => (
          <StepRow key={step.key} step={step} />
        ))}
      </ul>

      {/* Footer */}
      <footer
        className="flex items-center justify-between gap-4 px-6 py-3.5"
        style={{
          background: 'var(--surface-container-low, #f1f4f6)',
          borderTop: '1px solid var(--outline-variant, #abb3b7)',
          borderRadius: '0 0 24px 24px',
        }}
      >
        <div
          className="flex items-center gap-1.5"
          style={{
            fontSize: 11.5,
            color: 'var(--on-surface-variant, #586064)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13 }}
            aria-hidden
          >
            lock
          </span>
          Scanners run in an isolated sandbox · we never store your source
          code.
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onViewLiveLog}
            className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-on-surface-variant hover:bg-surface-container"
            style={{ fontSize: 12, fontWeight: 600 }}
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 14 }}
              aria-hidden
            >
              terminal
            </span>
            View live log
          </button>
          <button
            type="button"
            onClick={onConfigureScanners}
            className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-on-surface-variant hover:bg-surface-container"
            style={{ fontSize: 12, fontWeight: 600 }}
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 14 }}
              aria-hidden
            >
              settings
            </span>
            Configure scanners
          </button>
        </div>
      </footer>
    </section>
  )
}

function ScannerPill({ tool }: { tool: ScannerToolLike }) {
  const state = tool.state ?? 'pending'
  if (state === 'done' || state === 'skipped') {
    return (
      <span
        data-testid={`scanner-pill-${tool.id}`}
        data-state={state}
        className="inline-flex items-center gap-1.5 rounded-full"
        style={{
          padding: '6px 12px',
          fontSize: 11.5,
          fontWeight: 600,
          background: 'var(--surface-container-high, #e3e9ec)',
          color: 'var(--on-surface-variant, #586064)',
        }}
      >
        <span
          className="material-symbols-outlined"
          style={{
            fontSize: 13,
            fontVariationSettings: '"FILL" 1, "wght" 500',
          }}
          aria-hidden
        >
          check
        </span>
        {tool.label}
      </span>
    )
  }
  if (state === 'active') {
    return (
      <span
        data-testid={`scanner-pill-${tool.id}`}
        data-state={state}
        className="inline-flex items-center gap-1.5 rounded-full"
        style={{
          padding: '6px 12px',
          fontSize: 11.5,
          fontWeight: 600,
          background: 'var(--primary-container, #e2dfff)',
          color: 'var(--on-primary-container, #3f33d6)',
        }}
      >
        <span
          className="opensec-pulse-dot rounded-full"
          style={{
            width: 6,
            height: 6,
            background: 'var(--primary, #4d44e3)',
          }}
          aria-hidden
        />
        {tool.label}
      </span>
    )
  }
  return (
    <span
      data-testid={`scanner-pill-${tool.id}`}
      data-state={state}
      className="inline-flex items-center gap-1.5 rounded-full"
      style={{
        padding: '6px 12px',
        fontSize: 11.5,
        fontWeight: 600,
        background: 'var(--surface-container-high, #e3e9ec)',
        color: 'var(--on-surface-variant, #586064)',
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: 13 }}
        aria-hidden
      >
        {tool.icon || 'extension'}
      </span>
      {tool.label}
    </span>
  )
}

function StepRow({ step }: { step: StepLike }) {
  const state = step.state
  if (state === 'done') {
    return (
      <li
        data-testid={`step-row-${step.key}`}
        data-state="done"
        className="flex items-center gap-3 py-2.5 px-5 rounded-xl"
      >
        <span
          className="material-symbols-outlined"
          style={{
            fontSize: 18,
            color: 'var(--tertiary, #575e78)',
            fontVariationSettings: '"FILL" 1, "wght" 500',
          }}
          aria-hidden
        >
          check_circle
        </span>
        <span
          style={{ fontSize: 13, color: 'var(--on-surface, #2b3437)' }}
        >
          {step.label}
        </span>
        {step.result_summary && (
          <span
            className="ml-auto rounded-full font-mono"
            style={{
              fontSize: 10.5,
              padding: '2px 8px',
              background: 'var(--surface-container-high, #e3e9ec)',
              color: 'var(--on-surface-variant, #586064)',
            }}
          >
            {step.result_summary}
          </span>
        )}
      </li>
    )
  }
  if (state === 'running') {
    const pct = step.progress_pct ?? 0
    return (
      <li
        data-testid={`step-row-${step.key}`}
        data-state="running"
        className="rounded-xl p-4 my-1"
        style={{
          background: 'var(--primary-container, #e2dfff)',
          color: 'var(--on-primary-container, #3f33d6)',
        }}
      >
        <div className="flex items-center gap-3">
          <span
            className="opensec-spinner"
            style={{ width: 14, height: 14 }}
            aria-hidden
          />
          <span
            className="font-semibold"
            style={{ fontSize: 13.5, color: 'var(--on-surface, #2b3437)' }}
          >
            {step.label}
          </span>
          <span
            className="ml-auto font-bold tabular-nums"
            style={{ fontSize: 12, color: 'var(--primary, #4d44e3)' }}
          >
            {pct}%
          </span>
        </div>
        <div
          className="ml-7 mt-2 h-1.5 rounded-full overflow-hidden"
          style={{ background: 'rgba(77, 68, 227, 0.15)' }}
        >
          <div
            className="h-full"
            style={{
              width: `${Math.max(0, Math.min(100, pct))}%`,
              background: 'var(--primary, #4d44e3)',
              transition: 'width 200ms cubic-bezier(.2, 0, 0, 1)',
            }}
          />
        </div>
        {step.detail && (
          <div
            className="ml-7 mt-1.5"
            style={{
              fontSize: 12,
              color: 'var(--on-primary-container, #3f33d6)',
              opacity: 0.8,
            }}
          >
            {step.detail}
          </div>
        )}
      </li>
    )
  }
  // pending / skipped fallback
  return (
    <li
      data-testid={`step-row-${step.key}`}
      data-state={state}
      className="flex items-center gap-3 py-2.5 px-5 rounded-xl"
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: 16, color: 'var(--outline-variant, #abb3b7)' }}
        aria-hidden
      >
        radio_button_unchecked
      </span>
      <span
        style={{
          fontSize: 13,
          color: 'var(--on-surface-variant, #586064)',
          opacity: 0.8,
        }}
      >
        {step.label}
      </span>
      {step.hint && (
        <span
          className="ml-auto font-mono"
          style={{
            fontSize: 10.5,
            color: 'var(--on-surface-variant, #586064)',
            opacity: 0.6,
          }}
        >
          {step.hint}
        </span>
      )}
    </li>
  )
}

// ───────────────────── helpers ─────────────────────

function useElapsedSeconds(startedAt: string | null | undefined): number {
  const [elapsed, setElapsed] = useState(() => computeElapsed(startedAt))
  // Re-key the timer on ``startedAt`` so a new assessment id resets the
  // displayed elapsed without firing setState inside the effect body.
  useEffect(() => {
    const handle = setInterval(() => {
      setElapsed(computeElapsed(startedAt))
    }, 1000)
    return () => clearInterval(handle)
  }, [startedAt])
  return elapsed
}

function computeElapsed(startedAt: string | null | undefined): number {
  if (!startedAt) return 0
  const t = Date.parse(startedAt)
  if (Number.isNaN(t)) return 0
  return Math.max(0, Math.floor((Date.now() - t) / 1000))
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function computeStepCounter(steps: StepLike[]): string {
  if (steps.length === 0) return ''
  const total = steps.length
  const doneCount = steps.filter((s) => s.state === 'done').length
  const runningIdx = steps.findIndex((s) => s.state === 'running')
  const current = runningIdx >= 0 ? runningIdx + 1 : doneCount + 1
  return `Step ${Math.min(current, total)} of ${total}`
}

function humanizeRepo(repoUrl: string | null): string {
  if (!repoUrl) return 'your repository'
  try {
    const u = new URL(repoUrl)
    const path = u.pathname.replace(/^\/+|\.git$|\/+$/g, '')
    return path.split('/').pop() || repoUrl
  } catch {
    return repoUrl
  }
}
