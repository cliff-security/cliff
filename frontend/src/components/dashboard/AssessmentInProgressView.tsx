/**
 * AssessmentInProgressView — the unified "running" surface
 * (PRD-0003 v0.2 / surfaces/assessment-progress.jsx).
 *
 * One canvas, two callers: onboarding's first assessment and the
 * dashboard's re-assessment both render this. The shape is the
 * Serene Sentinel "editorial assurance" pattern — generous negative
 * space, a single rounded-3xl card, and a kinetic radar hero that
 * tells the user something real is happening without screaming about it.
 *
 *   ┌────────────────────────────────────────────────────────────────┐
 *   │  ◉  ┌──────────────────────────────────────┐  ELAPSED         │
 *   │ ░░  │ Headline                             │  01:24           │
 *   │     │ Description                          │                  │
 *   │     └──────────────────────────────────────┘                  │
 *   │                                                                │
 *   │  ──────────────────────────────────────────────────────────── │
 *   │  POWERED BY                                                    │
 *   │  [Trivy 0.52]  [Semgrep 1.70]  [15 posture checks]            │
 *   │                                                                │
 *   │  ─ Step 1 ──────────────────────────────────────  done         │
 *   │  ─ Step 2 ──────────────────────────────────────  running 42%  │
 *   │  ─ Step 3 ──────────────────────────────────────  pending      │
 *   │                                                                │
 *   │  [actions slot — wizard nav / re-assess buttons / etc.]        │
 *   └────────────────────────────────────────────────────────────────┘
 */

import { useEffect, useState } from 'react'

import { useAssessmentStatus } from '@/api/dashboard'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'
import AssessmentProgressList from './AssessmentProgressList'
import ToolPillBar from './ToolPillBar'

export interface AssessmentInProgressViewProps {
  assessmentId: string | null | undefined
  /** Hero headline. Defaults to "Assessment in progress". */
  headline?: string
  /** Sub-line under the headline. */
  description?: string
  /** ISO timestamp when the assessment started — drives the elapsed-time read-out.
   *  Falls back to the component's mount time when absent. */
  startedAt?: string | null
  /** Slot rendered below the step list — wizard nav, re-assess button, etc. */
  actions?: React.ReactNode
}

export default function AssessmentInProgressView({
  assessmentId,
  headline = 'Assessment in progress',
  description = 'Cliff is cloning your repo, scanning dependencies, sweeping for secrets, and walking the 15 posture checks. Stay here or come back — progress is saved.',
  startedAt,
  actions,
}: AssessmentInProgressViewProps) {
  const { data, isError } = useAssessmentStatus(assessmentId)
  const status = data?.status
  const tools = data?.tools ?? []
  const elapsed = useElapsed(startedAt ?? null)

  return (
    <div className="flex flex-col gap-5">
      <section
        role="status"
        aria-live="polite"
        aria-label="Assessment in progress"
        className="rounded-3xl bg-surface-container-lowest px-8 py-9 sm:px-10 sm:py-10"
      >
        <RadarHero
          headline={headline}
          description={description}
          elapsed={elapsed}
          status={status}
        />

        {tools.length > 0 && (
          <div
            data-testid="assessment-progress-tool-credits"
            className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-3 pt-5"
            style={{
              // Ghost separator (no 1px solid borders — Serene Sentinel
              // §No-Line Rule). 6% indigo on the inset edge.
              boxShadow: 'inset 0 1px 0 rgba(77, 68, 227, 0.06)',
            }}
          >
            <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Powered by
            </span>
            <ToolPillBar tools={tools} size="sm" />
          </div>
        )}

        <div className="mt-8">
          {assessmentId ? (
            <AssessmentProgressList
              assessmentId={assessmentId}
              chromeless
            />
          ) : null}
        </div>
      </section>

      {status === 'failed' && (
        <InlineErrorCallout
          title="Assessment failed"
          body={
            <>
              Something went wrong during the scan. The dashboard will pick up
              the failure and show what we managed to capture; you can re-run
              the assessment from there.
            </>
          }
        />
      )}

      {isError && (
        <InlineErrorCallout
          title="We couldn't read the assessment status"
          body={
            <>
              Check the backend logs, then refresh — the assessment itself is
              still running in the background.
            </>
          }
        />
      )}

      {actions ? <div>{actions}</div> : null}
    </div>
  )
}

// --------------------------------------------------------------------- hero

function RadarHero({
  headline,
  description,
  elapsed,
  status,
}: {
  headline: string
  description: string
  elapsed: string
  status?: string
}) {
  const isFailed = status === 'failed'
  const isComplete = status === 'complete'
  return (
    <div className="flex items-start gap-5">
      <RadarIcon failed={isFailed} complete={isComplete} />
      <div className="flex-1 min-w-0">
        <h2 className="font-headline text-2xl font-extrabold tracking-tight text-on-surface sm:text-[28px]">
          {headline}
        </h2>
        <p className="mt-1.5 max-w-[52ch] text-sm leading-relaxed text-on-surface-variant">
          {description}
        </p>
      </div>
      <div className="flex flex-col items-end text-right" aria-live="off">
        <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
          Elapsed
        </span>
        <span className="font-headline text-lg font-bold tabular-nums text-on-surface">
          {elapsed}
        </span>
      </div>
    </div>
  )
}

function RadarIcon({ failed, complete }: { failed: boolean; complete: boolean }) {
  // Editorial assurance: a soft primary-container square holding either
  // a rotating radar (default), a check_circle (complete), or a cancel
  // (failed). The square is rounded-2xl, not a circle, so it reads as
  // "instrument panel" rather than "loading spinner".
  let icon = 'radar'
  let iconClass = 'animate-spin text-primary'
  let frameClass = 'bg-primary-container'
  if (complete) {
    icon = 'check_circle'
    iconClass = 'text-tertiary'
    frameClass = 'bg-tertiary-container/55'
  } else if (failed) {
    icon = 'cancel'
    iconClass = 'text-error'
    frameClass = 'bg-error-container/40'
  }
  return (
    <span
      data-testid="assessment-progress-hero-icon"
      data-status={complete ? 'complete' : failed ? 'failed' : 'running'}
      className={`grid h-14 w-14 flex-shrink-0 place-items-center rounded-2xl ${frameClass}`}
    >
      <span
        className={`material-symbols-outlined ${iconClass}`}
        style={{
          fontSize: 28,
          ...(complete ? { fontVariationSettings: "'FILL' 1" } : undefined),
        }}
        aria-hidden
      >
        {icon}
      </span>
    </span>
  )
}

// --------------------------------------------------------------------- elapsed

function useElapsed(startedAt: string | null): string {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  const startMs = parseStart(startedAt)
  const seconds = Math.max(0, Math.floor((now - startMs) / 1000))
  return formatElapsed(seconds)
}

function parseStart(startedAt: string | null): number {
  if (!startedAt) return Date.now()
  const parsed = Date.parse(startedAt)
  return Number.isFinite(parsed) ? parsed : Date.now()
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
