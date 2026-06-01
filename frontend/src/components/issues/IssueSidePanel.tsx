/**
 * IssueSidePanel — PRD-0006 Phase 2 / IMPL-0007 §F1+F3+F4+F5+F6.
 *
 * 480px right-edge drawer that replaces the standalone Workspace page as the
 * only depth surface for an issue. Driven entirely by the issue's derived
 * stage:
 *
 *   - section ordering inside the body is stage-aware (Plan first when Plan
 *     ready, PR first when PR ready, Validation first when Done — see
 *     ``sectionsForStage`` below)
 *   - sticky footer is always 72px tall and swaps content per stage
 *   - the Refine flow lives inline in the Plan section; the Reject reason
 *     picker lives inline in the footer (no modal in either case)
 *
 * The component is read-mostly: ``useFindings`` already drives the row data
 * on the parent IssuesPage, and the panel re-uses that single source of
 * truth via the ``finding`` prop. Workspace-scoped data (sidebar + agent
 * runs) is loaded lazily via existing hooks when a workspace exists.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { parseApiError } from '../../api/client'
import type { AgentRun, ExceptionReason, Finding, IssueStage } from '../../api/client'
import {
  useAgentRuns,
  useApprovePlan,
  useCancelAgentRun,
  useExecuteAgent,
  useRejectFinding,
  useRespondToPermission,
  useRunAllPipeline,
  useSidebar,
  useUpdateFinding,
} from '../../api/hooks'
import { friendlyPermissionError } from '../../lib/permissionErrorMessage'
import { useAIRequired } from '../../api/aiProvider'
import { useOpenAIProvider } from '../ai-provider'
import { CliffSpinner } from '../CliffSpinner'
import Markdown from '../Markdown'
import { IssueFilterChip } from './IssueFilterChip'
import { IssueSeverityBadge, type IssueSeverityKind } from './IssueSeverityBadge'
import { IssueStageChip } from './IssueStageChip'

interface IssueSidePanelProps {
  finding: Finding
  onClose: () => void
  /** Invoked when the user clicks Start from the footer at stage='todo'. */
  onStart?: () => void
  /** True while the parent's POST /api/workspaces is in flight. */
  starting?: boolean
}

type SectionKey = 'plan' | 'plan_drafting' | 'pr' | 'validation' | 'finding' | 'activity'

const REASON_OPTIONS: { value: ExceptionReason; label: string }[] = [
  { value: 'false_positive', label: 'False positive' },
  { value: 'wont_fix', label: "Won't fix" },
  { value: 'accepted_risk', label: 'Accept risk' },
  { value: 'deferred', label: 'Defer' },
]

function severityKind(raw: string | null): IssueSeverityKind {
  const key = (raw ?? 'medium').toLowerCase()
  if (key === 'critical' || key === 'high' || key === 'low') return key
  return 'medium'
}

function sectionsForStage(stage: IssueStage): SectionKey[] {
  // ``activity`` (the agent-run history) is always positioned above
  // ``finding`` so the user lands on what Cliff has produced first, with
  // the static finding metadata as supporting context underneath. The
  // PR / Plan / Validation cards stay above ``activity`` because they're
  // the actionable surfaces.
  if (stage === 'plan_ready') return ['plan', 'activity', 'finding']
  // Awaiting approval: activity-first so the user sees what the agent was
  // doing right before it paused (the failed step, if any, is in activity);
  // the plan itself is the supporting context — they already approved it
  // earlier, the decision now is about ONE command.
  if (stage === 'awaiting_permission') return ['activity', 'plan', 'finding']
  // Failed / executor_failed: surface the most recent error context
  // (activity) at the top so the user lands on the actual reason, with
  // the plan still available below if they want to retry. No PR exists
  // in either state by definition.
  if (stage === 'failed' || stage === 'executor_failed') {
    return ['activity', 'plan', 'finding']
  }
  if (stage === 'pr_ready' || stage === 'pr_awaiting_val') {
    return ['pr', 'plan', 'activity', 'finding']
  }
  if (
    stage === 'fixed' ||
    stage === 'false_positive' ||
    stage === 'wont_fix' ||
    stage === 'accepted' ||
    stage === 'deferred'
  ) {
    return ['validation', 'pr', 'plan', 'activity', 'finding']
  }
  if (
    stage === 'planning' ||
    stage === 'generating' ||
    stage === 'pushing' ||
    stage === 'opening_pr' ||
    stage === 'validating'
  ) {
    return ['plan_drafting', 'activity', 'finding']
  }
  // todo
  return ['activity', 'finding']
}

export function IssueSidePanel({
  finding,
  onClose,
  onStart,
  starting,
}: IssueSidePanelProps) {
  const serverStage: IssueStage = finding.derived?.stage ?? 'todo'
  const workspaceId = finding.derived?.workspace_id ?? null
  // Q01R-W2 / B35b — derive the effective stage from the latest
  // remediation_executor run. The backend stage derivation can land on
  // ``pushing`` when the executor returned status='completed' but its
  // structured_output reports ``error_details`` (the local branch was
  // created but the actual git-push failed); the run never flips to
  // status='failed', so the backend never reaches the ``failed``
  // branch. We override the stage in the FRONTEND so the header pill,
  // top widget, and footer button surface a terminal-error treatment
  // instead of an indefinite "Pushing branch / Thinking…" spinner.
  const { data: agentRunsForStage } = useAgentRuns(workspaceId ?? undefined)
  const stage = useEffectiveStage(serverStage, agentRunsForStage ?? null)
  const sections = useMemo(() => sectionsForStage(stage), [stage])

  const [refining, setRefining] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const panelRef = useRef<HTMLElement | null>(null)

  const closePanel = useCallback(() => {
    setRefining(false)
    setRejecting(false)
    onClose()
  }, [onClose])

  // Esc closes (only when neither inline state owns the key — those handle
  // their own Esc to exit just the substate).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !refining && !rejecting) {
        closePanel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closePanel, refining, rejecting])

  // Outside-click closes. The mockup has a non-modal overlay; keep it
  // unobtrusive (no backdrop) and detect clicks via document-level listener.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (panelRef.current && target && !panelRef.current.contains(target)) {
        closePanel()
      }
    }
    // Defer registration to the next tick so the click that opened the panel
    // doesn't immediately close it.
    const handle = window.setTimeout(
      () => document.addEventListener('mousedown', onClick),
      0,
    )
    return () => {
      window.clearTimeout(handle)
      document.removeEventListener('mousedown', onClick)
    }
  }, [closePanel])

  // ADR-0047 / PR #2 — the agent-execution SSE channel is gone. It was
  // only ever a refetch *nudge* over the polled ``agent-runs`` query (3s
  // while a run is active / 5s idle), which is and always was the source
  // of truth: the permission prompt renders from
  // ``runningRun.permission_request`` and the activity feed from the
  // agent_run rows — both already polled. With the executor now parking a
  // durable DeferredToolRequests marker on the row, the poll surfaces the
  // approval prompt and run-status transitions within one interval, so no
  // push channel is needed. (The chat SSE — api.streamWorkspaceEvents — is
  // unrelated and stays.)

  return (
    <aside
      ref={panelRef}
      role="dialog"
      aria-label={`Issue details — ${finding.title}`}
      className="fixed right-0 top-0 bottom-0 z-30 flex flex-col"
      style={{
        width: 480,
        background: 'var(--cd-bg-1)',
        borderLeft: '1px solid var(--cd-rule)',
        boxShadow: '-16px 0 40px rgba(0,0,0,0.45)',
      }}
    >
      <SidePanelHeader finding={finding} stage={stage} onClose={closePanel} />

      <div className="flex-1 overflow-y-auto">
        {sections.map((key) => {
          if (key === 'plan')
            return (
              <SPPlan
                key={key}
                finding={finding}
                refining={refining}
                onRefineCancel={() => setRefining(false)}
                onRefineSubmitted={() => setRefining(false)}
              />
            )
          if (key === 'plan_drafting')
            return <SPPlanDrafting key={key} stage={stage} />
          if (key === 'pr')
            return <SPPullRequest key={key} prUrl={finding.derived?.pr_url ?? null} />
          if (key === 'validation') return <SPValidation key={key} stage={stage} />
          if (key === 'finding') return <SPFinding key={key} finding={finding} />
          return <SPActivity key={key} workspaceId={workspaceId} />
        })}
      </div>

      <SidePanelFooter
        finding={finding}
        stage={stage}
        rejecting={rejecting}
        onRefine={() => {
          setRejecting(false)
          setRefining(true)
        }}
        onRejectStart={() => {
          setRefining(false)
          setRejecting(true)
        }}
        onRejectCancel={() => setRejecting(false)}
        onRejected={closePanel}
        onStart={onStart}
        starting={starting}
      />
    </aside>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function SidePanelHeader({
  finding,
  stage,
  onClose,
}: {
  finding: Finding
  stage: IssueStage
  onClose: () => void
}) {
  const sev = severityKind(finding.raw_severity)
  const file = (finding.raw_payload?.file as string | undefined) ?? null
  const line = (finding.raw_payload?.line as number | string | undefined) ?? null

  return (
    <header
      className="flex-shrink-0"
      style={{
        padding: '18px 20px 14px',
        borderBottom: '1px solid var(--cd-rule)',
        background: 'var(--cd-bg-1)',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <IssueSeverityBadge kind={sev} size="sm" />
        <IssueStageChip kind={stage} size="sm" />
        <span
          className="font-mono ml-auto"
          style={{ fontSize: 10.5, color: 'var(--cd-fg-4)', letterSpacing: '0.08em' }}
        >
          {finding.id.toUpperCase()}
        </span>
        <span
          className="cd-key"
          aria-hidden
          title="Esc closes"
          style={{ marginLeft: 6 }}
        >
          esc
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="cd-btn cd-btn--ghost cd-btn--sm"
          style={{ padding: '4px 6px', minWidth: 0 }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
            close
          </span>
        </button>
      </div>
      {/* Type / file meta sits ABOVE the title as a quiet eyebrow line —
       *  critique round 2: the meta was orphaned under the H2; pulling
       *  it up establishes context before the title and lets the H2
       *  carry the heading job cleanly. */}
      <div
        className="cd-section-label cd-section-label--quiet"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          marginBottom: 8,
        }}
      >
        <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>
          {finding.type === 'posture' ? 'verified_user' : 'bug_report'}
        </span>
        <span>{(finding.type ?? 'vulnerability').charAt(0).toUpperCase() + (finding.type ?? 'vulnerability').slice(1)}</span>
        {file && (
          <>
            <span style={{ color: 'var(--cd-fg-5)' }}>·</span>
            <span className="font-mono" style={{ color: 'var(--cd-cyan)' }}>
              {file}
              {line != null ? `:${line}` : ''}
            </span>
          </>
        )}
      </div>
      <h2
        className="font-display font-extrabold"
        style={{
          fontSize: 20,
          color: 'var(--cd-fg-1)',
          letterSpacing: '-0.02em',
          lineHeight: 1.25,
          margin: 0,
        }}
      >
        {finding.title}
      </h2>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Section primitives
// ---------------------------------------------------------------------------

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  // Sentence-case sub-section labels per the readability brief (E2).
  // Lowercase incoming caps so existing call sites (which pass
  // "FINDING", "ACTIVITY", etc.) render as "Finding", "Activity".
  const sentence =
    title.length > 0
      ? title.charAt(0).toUpperCase() + title.slice(1).toLowerCase()
      : title
  return (
    <div className="flex items-baseline gap-3 mb-3">
      <h3 className="cd-section-label cd-section-label--quiet">{sentence}</h3>
      {hint && (
        <span style={{ fontSize: 12, color: 'var(--cd-fg-4)' }}>{hint}</span>
      )}
    </div>
  )
}

function SPPlan({
  finding,
  refining,
  onRefineCancel,
  onRefineSubmitted,
}: {
  finding: Finding
  refining: boolean
  onRefineCancel: () => void
  onRefineSubmitted: () => void
}) {
  const workspaceId = finding.derived?.workspace_id ?? null
  const { data: sidebar } = useSidebar(workspaceId ?? undefined)
  // The remediation_planner emits ``{"plan_steps": ["step 1", "step 2", ...]}``
  // (flat list of strings). Older code expected ``{"steps": [{title, file}]}``
  // and rendered "no plan yet" for every real plan. Read both shapes so
  // historical sidebars don't silently regress, and normalize each step
  // into the ``{title, file?}`` object the JSX below renders.
  const rawPlan = sidebar?.plan as
    | {
        plan_steps?: (string | { title?: string; file?: string })[]
        steps?: { title?: string; file?: string }[]
      }
    | undefined
  const planSteps: { title?: string; file?: string }[] = (
    rawPlan?.plan_steps ??
    rawPlan?.steps ??
    []
  ).map((s) => (typeof s === 'string' ? { title: s } : s))

  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle title="Plan" />
      {planSteps.length > 0 ? (
        <ol className="space-y-2.5">
          {planSteps.map((step, i) => (
            <li key={i} className="flex items-start gap-3">
              <span
                className="flex items-center justify-center rounded-full font-mono font-semibold flex-shrink-0 mt-0.5 bg-primary-container text-on-primary-container"
                style={{ width: 22, height: 22, fontSize: 10.5 }}
              >
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] text-on-surface">{step.title ?? `Step ${i + 1}`}</div>
                {step.file && (
                  <div className="text-[11px] text-on-surface-variant mt-1 font-mono">{step.file}</div>
                )}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[12.5px] text-on-surface-variant">
          The planner has not produced a plan yet.
        </p>
      )}

      {refining && (
        <SidePanelRefineCallout
          workspaceId={workspaceId}
          onCancel={onRefineCancel}
          onSubmitted={onRefineSubmitted}
        />
      )}
    </section>
  )
}

function SidePanelRefineCallout({
  workspaceId,
  onCancel,
  onSubmitted,
}: {
  workspaceId: string | null
  onCancel: () => void
  onSubmitted: () => void
}) {
  const [note, setNote] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const executeAgent = useExecuteAgent(workspaceId ?? undefined)
  const aiRequired = useAIRequired()
  const { open: openAIProvider } = useOpenAIProvider()
  const blockedByAI = !aiRequired.enabled && !aiRequired.loading

  useEffect(() => {
    // Defer focus to ensure the textarea has mounted.
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }, [])

  const sending = executeAgent.isPending

  return (
    <div
      className="mt-4 rounded-xl p-3 flex items-start gap-2.5"
      style={{ background: 'var(--primary-container)' }}
    >
      <span
        className="material-symbols-outlined text-on-primary-container mt-0.5"
        style={{ fontSize: 18 }}
        aria-hidden
      >
        edit_note
      </span>
      <div className="flex-1">
        <div className="text-[11px] uppercase tracking-wider text-on-primary-container font-bold mb-1.5">
          Refining plan
        </div>
        <textarea
          ref={textareaRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault()
              e.stopPropagation()
              onCancel()
            }
          }}
          placeholder="Tell the planner what to change"
          rows={3}
          className="w-full bg-surface-container-lowest rounded-lg p-2.5 text-[12.5px] text-on-surface outline-none resize-none"
          style={{ border: '1px solid var(--outline-variant)' }}
        />
        <div className="flex items-center justify-end gap-2 mt-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-2.5 py-1.5 text-[12px] font-semibold rounded-lg text-on-surface hover:bg-surface-container"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!workspaceId || !note.trim() || sending}
            onClick={() => {
              if (blockedByAI) {
                openAIProvider()
                return
              }
              if (!workspaceId) return
              executeAgent.mutate(
                { agentType: 'remediation_planner', user_note: note.trim() },
                { onSuccess: () => onSubmitted() },
              )
            }}
            title={blockedByAI ? aiRequired.tooltip ?? undefined : undefined}
            aria-disabled={blockedByAI}
            className="px-2.5 py-1.5 text-[12px] font-semibold rounded-lg bg-primary text-on-primary disabled:opacity-50 hover:bg-primary-dim inline-flex items-center gap-1"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
              send
            </span>
            Send to agent
          </button>
        </div>
      </div>
    </div>
  )
}

function SPPlanDrafting({ stage }: { stage: IssueStage }) {
  const labels: Partial<Record<IssueStage, string>> = {
    planning: 'Reviewing the advisory and the call sites…',
    generating: 'Generating the patch…',
    pushing: 'Pushing the branch to GitHub…',
    opening_pr: 'Opening the pull request…',
    validating: 'Re-running the validator against the latest commit…',
  }
  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle title="Plan" hint="Thinking…" />
      <div
        className="rounded-xl p-4 flex items-start gap-3"
        style={{ background: 'var(--primary-container)' }}
      >
        <CliffSpinner size={20} label="Cliff is thinking" />
        <div className="flex-1">
          <div className="text-[12.5px] font-semibold text-on-primary-container mb-1">
            {labels[stage] ?? 'Working on the fix…'}
          </div>
          <div className="text-[11.5px] text-on-primary-container/80">
            We&rsquo;ll surface the result here when it&rsquo;s ready.
          </div>
        </div>
      </div>
    </section>
  )
}

function SPPullRequest({ prUrl }: { prUrl: string | null }) {
  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle title="Pull request" />
      {prUrl ? (
        <a
          href={prUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-primary hover:underline"
        >
          {prUrl}
          <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
            north_east
          </span>
        </a>
      ) : (
        <p className="text-[12.5px] text-on-surface-variant">No pull request yet.</p>
      )}
    </section>
  )
}

function SPValidation({ stage }: { stage: IssueStage }) {
  const verdict =
    stage === 'fixed'
      ? 'Fix verified'
      : stage === 'false_positive'
        ? 'Marked as false positive'
        : stage === 'wont_fix'
          ? "Marked won't fix"
          : stage === 'accepted'
            ? 'Risk accepted'
            : stage === 'deferred'
              ? 'Deferred'
              : 'Closed'
  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle title="Validation" />
      <div
        className="rounded-xl p-4 bg-tertiary-container text-on-tertiary-container"
      >
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 18, fontVariationSettings: "'FILL' 1" }}
            aria-hidden
          >
            check_circle
          </span>
          <span className="text-[13px] font-bold">{verdict}</span>
        </div>
        {stage === 'fixed' && (
          // "Mark as fixed" closes the finding in Cliff's DB but doesn't
          // re-verify the underlying rubric — that flips on the next
          // assessment. Without this hint the unchanged grade after a
          // close reads as a Cliff bug.
          <div
            className="text-[11.5px] mt-1 opacity-80"
            data-testid="validation-rerun-hint"
          >
            We&rsquo;ll confirm this on the next assessment. Re-run from the
            Dashboard to refresh the grade.
          </div>
        )}
      </div>
    </section>
  )
}

function SPFinding({ finding }: { finding: Finding }) {
  const cwe = (finding.raw_payload?.cwe as string | undefined) ?? null
  const cvss = (finding.raw_payload?.cvss as number | undefined) ?? null
  const file = (finding.raw_payload?.file as string | undefined) ?? null
  const line = (finding.raw_payload?.line as number | string | undefined) ?? null
  const found = (finding.raw_payload?.found as string | undefined) ?? null

  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle title="Finding" />
      <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-[12px]">
        <dt className="text-on-surface-variant">CWE</dt>
        <dd className="font-mono text-on-surface">{cwe ?? '—'}</dd>
        {cvss != null && (
          <>
            <dt className="text-on-surface-variant">CVSS</dt>
            <dd className="font-mono text-on-surface">{cvss}</dd>
          </>
        )}
        <dt className="text-on-surface-variant">Source</dt>
        <dd className="text-on-surface">{finding.source_type}</dd>
        {file && (
          <>
            <dt className="text-on-surface-variant">File</dt>
            <dd className="font-mono text-on-surface">
              {file}
              {line != null ? `:${line}` : ''}
            </dd>
          </>
        )}
        {found && (
          <>
            <dt className="text-on-surface-variant">Found</dt>
            <dd className="text-on-surface">{found}</dd>
          </>
        )}
      </dl>
      {finding.description && (
        <div className="mt-4 text-[12.5px] leading-relaxed">
          <Markdown content={finding.description} />
        </div>
      )}
    </section>
  )
}

const AGENT_LABEL: Record<string, string> = {
  finding_enricher: 'Enriching the finding',
  owner_resolver: 'Resolving owner',
  exposure_analyzer: 'Analyzing exposure',
  remediation_planner: 'Drafting the plan',
  remediation_executor: 'Applying the fix',
  validation_checker: 'Validating the fix',
  evidence_collector: 'Collecting evidence',
}

function agentLabel(type: string): string {
  return AGENT_LABEL[type] ?? type.replace(/_/g, ' ')
}

function durationLabel(started: string | null, ended: string | null): string | null {
  if (!started) return null
  const start = Date.parse(started)
  const end = ended ? Date.parse(ended) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null
  const secs = Math.round((end - start) / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  return secs % 60 === 0 ? `${mins}m` : `${mins}m ${secs % 60}s`
}

function SPActivity({ workspaceId }: { workspaceId: string | null }) {
  const { data: runs } = useAgentRuns(workspaceId ?? undefined)

  if (!workspaceId) {
    return (
      <section
        className="px-5 py-5"
        style={{ borderBottom: '1px solid var(--outline-variant)' }}
      >
        <SectionTitle title="Activity" />
        <p className="text-[12px] text-on-surface-variant">
          Start the issue to begin its activity log.
        </p>
      </section>
    )
  }

  // Newest first. Falls back gracefully when ``started_at`` is null for queued
  // rows that haven't executed yet.
  const sorted = [...(runs ?? [])].sort((a, b) => {
    const aT = a.started_at ? Date.parse(a.started_at) : 0
    const bT = b.started_at ? Date.parse(b.started_at) : 0
    return bT - aT
  })

  return (
    <section
      className="px-5 py-5"
      style={{ borderBottom: '1px solid var(--outline-variant)' }}
    >
      <SectionTitle
        title="Activity"
        hint={
          sorted.length
            ? `${sorted.length} run${sorted.length === 1 ? '' : 's'}`
            : undefined
        }
      />
      {sorted.length === 0 ? (
        <p className="text-[12px] text-on-surface-variant">
          No agent runs yet — Cliff will populate this as it works.
        </p>
      ) : (
        <ol className="space-y-2.5">
          {sorted.map((run) => (
            <ActivityRunCard key={run.id} run={run} />
          ))}
        </ol>
      )}
    </section>
  )
}

/**
 * URL the activity card's "How to fix" link points to when an agent run
 * surfaces a structured ``error_details`` string. Kept in sync with the
 * backend route's ``GITHUB_APP_PERMS_DOC_URL`` constant
 * (``cliff/api/routes/agent_execution.py``) so the 412 preflight
 * response and the historical run cards both deep-link to the same
 * anchor in the setup guide.
 */
const GITHUB_APP_PERMS_DOC_URL =
  'https://github.com/cliff-security/cliff/blob/main/' +
  'docs/guides/setup-github-app.md#required-permissions'

/**
 * Heuristic: does this error_details string look like a GitHub
 * push / permission failure (the case the "How to fix" link actually
 * helps with)? The remediation_executor reports a wide range of
 * error_details — push denied, OAuth scope missing, but also unrelated
 * shapes like "Tool usage prohibited by current instruction" that the
 * permissions guide can't address. Showing the link blanket on every
 * ``error_details`` sent users to a doc that didn't match their
 * problem (and, until the URL fix that ships with this constant, to a
 * dead link).
 *
 * Matching is intentionally permissive: any of the listed substrings
 * triggers the link, lower-cased. False positives are cheaper than
 * false negatives — a misleading help link is a less bad outcome than
 * a real GitHub-App-perms failure with no guidance.
 */
function looksLikeGithubPermissionsError(errorDetails: string): boolean {
  const haystack = errorDetails.toLowerCase()
  return (
    haystack.includes('push') ||
    haystack.includes('permission') ||
    haystack.includes('denied') ||
    haystack.includes('403') ||
    haystack.includes('forbidden') ||
    haystack.includes('unauthorized') ||
    haystack.includes('401') ||
    haystack.includes('gh_token') ||
    haystack.includes('github token') ||
    haystack.includes('authentication') ||
    haystack.includes('access denied') ||
    haystack.includes('insufficient scope') ||
    haystack.includes('write permission') ||
    haystack.includes('write access')
  )
}

/**
 * Read ``structured_output.error_details`` off an agent run if present.
 *
 * The remediation_executor writes ``error_details`` into its structured
 * output whenever something fails after the LLM step but before the PR
 * is opened — most commonly the B30 case where the App-issued OAuth
 * token can't push to an org repo. We render that string inline rather
 * than letting the panel sit on "Thinking…" forever (B28-adjacent).
 */
function errorDetailsOf(run: AgentRun): string | null {
  const out = run.structured_output as
    | { error_details?: unknown }
    | null
    | undefined
  if (!out) return null
  const value = out.error_details
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

/**
 * Q01R-W2 / B35b — frontend stage override.
 *
 * The backend stage derivation maps a remediation_executor run with
 * status='completed' + ``structured_output.error_details`` to whatever
 * the sidebar's ``pull_request.status`` field implies (typically
 * ``pushing`` when only the branch_name is set) — which leaves the
 * panel sitting on "Pushing branch / Thinking…" indefinitely while the
 * activity log already shows the failure. We override here so the
 * user-facing stage matches the actual state of the world.
 *
 * Kept narrow on purpose: only fires when the MOST RECENT
 * remediation_executor run is in this terminal-error shape. A
 * successful re-run replaces the latest run and the override switches
 * off automatically. Other agent failures (planner, validator) keep
 * the existing ``failed`` path because the backend already maps them
 * correctly.
 */
function useEffectiveStage(
  serverStage: IssueStage,
  runs: AgentRun[] | null,
): IssueStage {
  return useMemo(() => {
    if (!runs || runs.length === 0) return serverStage
    // ``failed`` is already a terminal-error stage — no need to override.
    if (serverStage === 'failed' || serverStage === 'executor_failed') {
      return serverStage
    }
    // Find the latest remediation_executor run by started_at. A run
    // with status='completed' will always have started_at set (the
    // backend writes it before the run reaches a terminal status), so
    // we don't need a separate created_at fallback for the override
    // case below.
    let latestExecutor: AgentRun | null = null
    let latestTs = -Infinity
    for (const r of runs) {
      if (r.agent_type !== 'remediation_executor') continue
      const ts = r.started_at ? Date.parse(r.started_at) : 0
      if (Number.isFinite(ts) && ts > latestTs) {
        latestTs = ts
        latestExecutor = r
      }
    }
    if (
      latestExecutor &&
      latestExecutor.status === 'completed' &&
      errorDetailsOf(latestExecutor) != null
    ) {
      return 'executor_failed'
    }
    return serverStage
  }, [serverStage, runs])
}

function ActivityRunCard({ run }: { run: AgentRun }) {
  const label = agentLabel(run.agent_type)
  const duration = durationLabel(run.started_at, run.completed_at)
  const errorDetails = errorDetailsOf(run)
  const isFailed =
    run.status === 'failed' ||
    run.status === 'cancelled' ||
    run.status === 'rate_limited' ||
    errorDetails != null
  const isRunning = run.status === 'running' || run.status === 'queued'

  return (
    <li
      className="rounded-xl p-3"
      style={{
        background: isFailed
          ? 'rgba(239, 100, 100, 0.06)'
          : 'var(--surface-container-low, #f1f4f6)',
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="material-symbols-outlined"
          style={{
            fontSize: 14,
            color: isFailed
              ? 'var(--error, #ef6464)'
              : isRunning
                ? '#6FE3B5'
                : 'var(--on-surface-variant, #586064)',
          }}
          aria-hidden
        >
          {isFailed ? 'error' : isRunning ? 'autorenew' : 'check_circle'}
        </span>
        <span className="text-[12.5px] font-semibold text-on-surface flex-1 min-w-0 truncate">
          {label}
        </span>
        {run.confidence != null && !isFailed && (
          <span
            className="text-[10.5px] font-mono text-on-surface-variant"
            title="Agent confidence in its own output"
          >
            {Math.round(run.confidence * 100)}%
          </span>
        )}
        {duration && (
          <span className="text-[10.5px] font-mono text-on-surface-variant">
            {duration}
          </span>
        )}
      </div>
      {run.summary_markdown && !isRunning && !errorDetails && (
        <div className="mt-2 text-[11.5px] leading-relaxed text-on-surface-variant">
          <Markdown content={run.summary_markdown} />
        </div>
      )}
      {errorDetails && (
        // Inline error surface for an agent run whose structured_output
        // reports ``error_details``. Tonal layering (no 1px borders, no
        // pure black). The "How to fix" deep-link is gated by
        // ``looksLikeGithubPermissionsError`` because the link points
        // at the GitHub-App setup guide — useful for the B30 push /
        // permission case but misleading for unrelated error shapes
        // (e.g. "Tool usage prohibited by current instruction"), so we
        // only render it when the error text actually matches.
        <div
          className="mt-2 rounded-lg p-2.5"
          style={{
            background: 'rgba(239, 100, 100, 0.10)',
            color: 'var(--on-surface, #2b3437)',
          }}
        >
          <div className="text-[11.5px] leading-relaxed">{errorDetails}</div>
          {looksLikeGithubPermissionsError(errorDetails) && (
            <div className="mt-1.5">
              <a
                href={GITHUB_APP_PERMS_DOC_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11.5px] font-semibold hover:underline"
                style={{ color: 'var(--primary, #4d44e3)' }}
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontSize: 13 }}
                  aria-hidden
                >
                  help
                </span>
                How to fix
              </a>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------

function SidePanelFooter({
  finding,
  stage,
  rejecting,
  onRefine,
  onRejectStart,
  onRejectCancel,
  onRejected,
  onStart,
  starting,
}: {
  finding: Finding
  stage: IssueStage
  rejecting: boolean
  onRefine: () => void
  onRejectStart: () => void
  onRejectCancel: () => void
  onRejected: () => void
  onStart?: () => void
  starting?: boolean
}) {
  // ``minHeight: 72`` — the single-row footer stages (todo, planning,
  // plan_ready, pr_ready, fixed) sit at the 72-px design intent because
  // their content fits in one row; the existing height tests target
  // those. ``awaiting_permission`` is intentionally taller because its
  // content is a code block plus a separate actions row — a deliberate
  // pause moment that earns the extra vertical real estate.
  return (
    <footer
      data-testid="side-panel-footer"
      className="sticky bottom-0 left-0 right-0 z-10"
      style={{
        background: 'var(--cd-bg-1)',
        borderTop: '1px solid var(--cd-rule)',
        minHeight: 72,
        height:
          stage === 'awaiting_permission' && !rejecting ? 'auto' : 72,
        padding:
          stage === 'awaiting_permission' && !rejecting
            ? '0 20px'
            : '0 20px',
        display: 'flex',
        alignItems:
          stage === 'awaiting_permission' && !rejecting
            ? 'stretch'
            : 'center',
      }}
    >
      {rejecting ? (
        <RejectFooter
          finding={finding}
          onCancel={onRejectCancel}
          onRejected={onRejected}
        />
      ) : (
        <DefaultFooter
          finding={finding}
          stage={stage}
          onRefine={onRefine}
          onRejectStart={onRejectStart}
          onStart={onStart}
          starting={starting}
        />
      )}
    </footer>
  )
}

/**
 * Inline error surfaced under the "Approve & generate fix" / "Retry"
 * footer buttons.
 *
 * Its load-bearing case is the executor's 412 push-access preflight:
 * that response creates no agent run, so SPActivity has nothing to
 * render — without this the error vanishes and the button just flips
 * back to its idle label ("nothing happens" from the user's seat).
 *
 * Reads the backend's structured ``{reason, remediation_link}`` detail
 * when present, falling back to the generic parsed message.
 */
/** Accept only http/https URLs for the "How to fix" link target. The
 *  backend builds remediation_link, but rendering it straight into an
 *  ``<a href>`` would let an attacker-controlled or buggy upstream
 *  smuggle in ``javascript:`` or other unsafe schemes — a click on
 *  the link would then execute script. Bad URLs degrade to ``null``
 *  and the caller falls back to the static docs URL when applicable. */
function safeExternalHttpUrl(raw: string | null | undefined): string | null {
  if (!raw) return null
  try {
    const u = new URL(raw)
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.toString() : null
  } catch {
    return null
  }
}

function FooterActionError({ error }: { error: unknown }) {
  const { message, detail } = parseApiError(error)
  const obj =
    detail && typeof detail === 'object'
      ? (detail as { reason?: unknown; remediation_link?: unknown })
      : null
  const reason =
    obj && typeof obj.reason === 'string' && obj.reason.trim()
      ? obj.reason.trim()
      : message || 'Something went wrong — please try again.'
  const backendLink =
    obj && typeof obj.remediation_link === 'string'
      ? safeExternalHttpUrl(obj.remediation_link)
      : null
  const link =
    backendLink ??
    (looksLikeGithubPermissionsError(reason) ? GITHUB_APP_PERMS_DOC_URL : null)
  return (
    <div
      role="alert"
      data-testid="footer-action-error"
      className="flex items-start gap-2 w-full rounded-lg bg-surface-container-lowest px-3 py-2"
    >
      <span
        className="material-symbols-outlined text-error text-[16px] leading-none mt-[1px]"
        aria-hidden
      >
        error
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[12px] text-on-surface">{reason}</p>
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noreferrer"
            className="text-[11.5px] font-semibold text-primary hover:underline"
          >
            How to fix this
          </a>
        )}
      </div>
    </div>
  )
}

function DefaultFooter({
  finding,
  stage,
  onRefine,
  onRejectStart,
  onStart,
  starting,
}: {
  finding: Finding
  stage: IssueStage
  onRefine: () => void
  onRejectStart: () => void
  onStart?: () => void
  starting?: boolean
}) {
  const workspaceId = finding.derived?.workspace_id ?? null
  const executeAgent = useExecuteAgent(workspaceId ?? undefined)
  const approvePlan = useApprovePlan(workspaceId ?? undefined)
  const runAllPipeline = useRunAllPipeline(workspaceId ?? undefined)
  const cancelAgentRun = useCancelAgentRun(workspaceId ?? undefined)
  const respondToPermission = useRespondToPermission(workspaceId ?? undefined)
  const updateFinding = useUpdateFinding()
  const aiRequired = useAIRequired()
  const { open: openAIProvider } = useOpenAIProvider()
  const blockedByAI = !aiRequired.enabled && !aiRequired.loading
  const prUrl = finding.derived?.pr_url ?? null
  // The in-flight footer's "Cancel run" needs the id of the run actually
  // executing. There is at most one running run per workspace (the
  // AgentBusy guard enforces it), so first-match is correct.
  const { data: agentRuns } = useAgentRuns(workspaceId ?? undefined)
  const runningRun =
    agentRuns?.find((r) => r.status === 'running') ?? null

  if (stage === 'awaiting_permission') {
    const req = runningRun?.permission_request ?? null
    if (!req || !runningRun) {
      // Brief race — derive() saw the marker but our poll hasn't refreshed
      // yet. Render a non-actionable holding state so the footer never
      // blanks (which would let the user keep clicking through to other
      // affordances that don't apply right now).
      return (
        <div className="flex items-center gap-3 w-full">
          <CliffSpinner size={14} label="Loading approval details" />
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-semibold text-on-surface">
              Waiting for approval details
            </div>
            <div className="text-[11px] text-on-surface-variant">
              The agent paused on a command — fetching the details now.
            </div>
          </div>
        </div>
      )
    }
    return (
      <PermissionPrompt
        tool={req.tool}
        patterns={req.patterns}
        pending={respondToPermission.isPending}
        errorMessage={
          respondToPermission.isError
            ? friendlyPermissionError(respondToPermission.error)
            : null
        }
        onApprove={() =>
          respondToPermission.mutate({ runId: runningRun.id, approved: true })
        }
        onDeny={() =>
          respondToPermission.mutate({ runId: runningRun.id, approved: false })
        }
      />
    )
  }

  if (stage === 'todo') {
    return (
      <div className="flex items-center gap-2 w-full">
        <PrimaryButton
          icon="play_arrow"
          kbd="S"
          onClick={onStart}
          disabled={!onStart || starting}
        >
          {starting ? 'Starting…' : 'Start'}
        </PrimaryButton>
      </div>
    )
  }

  if (
    stage === 'planning' ||
    stage === 'generating' ||
    stage === 'pushing' ||
    stage === 'opening_pr' ||
    stage === 'validating'
  ) {
    return (
      <div className="flex items-center gap-3 w-full">
        <CliffSpinner size={14} label="Cliff is thinking" />
        <div className="flex-1 min-w-0">
          <div className="text-[12.5px] font-semibold text-on-surface">
            {stage === 'validating' ? 'Validating fix' : 'Thinking'}
          </div>
          <div className="text-[11px] text-on-surface-variant">
            We&rsquo;ll notify you when the next step is ready.
          </div>
        </div>
        <TextButton
          onClick={() => {
            if (runningRun) cancelAgentRun.mutate(runningRun.id)
          }}
          disabled={!runningRun || cancelAgentRun.isPending}
        >
          {cancelAgentRun.isPending ? 'Cancelling…' : 'Cancel run'}
        </TextButton>
      </div>
    )
  }

  if (stage === 'plan_ready') {
    const approvePending = approvePlan.isPending || executeAgent.isPending
    // A failed approve/execute — most importantly the executor's 412
    // push-access preflight, which creates no agent run and so would
    // otherwise vanish (the footer just flips back to its idle label).
    const actionError = executeAgent.error ?? approvePlan.error ?? null
    return (
      <div className="flex flex-col gap-2 w-full">
        <div className="flex items-center gap-2 w-full">
          <PrimaryButton
            icon="check_circle"
            kbd="A"
            onClick={() => {
              if (blockedByAI) {
                openAIProvider()
                return
              }
              if (!workspaceId) return
              // Clear a stale executor error from a prior attempt so the
              // footer only ever shows this attempt's failure (a fresh
              // ``approvePlan.mutate`` resets approvePlan itself).
              executeAgent.reset()
              // Q01R / B29 — flip ``plan.approved=true`` BEFORE kicking
              // the executor so the run-all loop's gate sees the approval
              // and the executor reads an approved plan from the sidebar.
              // Without the approve call first the executor either no-ops
              // (run-all path) or races against an un-approved plan.
              approvePlan.mutate(undefined, {
                onSuccess: () => {
                  executeAgent.mutate({ agentType: 'remediation_executor' })
                },
              })
            }}
            disabled={!workspaceId || approvePending}
            title={blockedByAI ? aiRequired.tooltip ?? undefined : undefined}
          >
            {approvePending ? 'Approving…' : 'Approve & generate fix'}
          </PrimaryButton>
          <TextButton kbd="R" onClick={onRefine}>
            Refine
          </TextButton>
          <span className="ml-auto" />
          <ErrorButton icon="block" kbd="X" onClick={onRejectStart}>
            Reject
          </ErrorButton>
        </div>
        {actionError != null && !approvePending && (
          <FooterActionError error={actionError} />
        )}
      </div>
    )
  }

  if (stage === 'failed' || stage === 'executor_failed') {
    // Latest agent run failed (timeout, engine unavailable, credits
    // exhausted, failed PR push, etc.) OR — for ``executor_failed`` —
    // the executor returned with ``error_details`` set after a partial
    // success (local branch created, push died at git-protocol level).
    // The actual reason is rendered by SPActivity right above this
    // footer; we just offer the two reasonable next steps: retry, or
    // reject the finding entirely.
    //
    // Retry semantics depend on WHERE the failure happened:
    //
    //  • ``executor_failed`` — plan already exists and was approved;
    //    re-fire the executor through the same approve-then-execute
    //    chain the plan_ready button uses (approvePlan is idempotent).
    //
    //  • ``failed`` — could be any forward-pipeline agent. If it's a
    //    pre-plan failure (enricher / owner / exposure / evidence —
    //    e.g. OpenRouter ran out of credits during enrichment) we
    //    cannot just re-run the executor; there is no plan yet, so it
    //    would re-fail immediately. Call ``runAllPipeline`` instead and
    //    let the backend's ``suggest_next`` re-fire whichever section
    //    is missing in the sidebar — works for both pre-plan and
    //    post-plan failures.
    const retryPending =
      approvePlan.isPending ||
      executeAgent.isPending ||
      runAllPipeline.isPending
    // A retry can fail the same way the first attempt did — surface it
    // (the executor's 412 preflight creates no run for SPActivity to show).
    const retryError =
      executeAgent.error ?? approvePlan.error ?? runAllPipeline.error ?? null
    return (
      <div className="flex flex-col gap-2 w-full">
        <div className="flex items-center gap-2 w-full">
          <PrimaryButton
            icon="refresh"
            kbd="R"
            onClick={() => {
              if (blockedByAI) {
                openAIProvider()
                return
              }
              if (!workspaceId) return
              // Reset the mutations this retry won't re-fire, so a stale
              // error from a prior attempt can't outrank this one in the
              // footer (the mutation being fired resets itself).
              if (stage === 'executor_failed') {
                executeAgent.reset()
                approvePlan.mutate(undefined, {
                  onSuccess: () => {
                    executeAgent.mutate({ agentType: 'remediation_executor' })
                  },
                })
              } else {
                approvePlan.reset()
                executeAgent.reset()
                runAllPipeline.mutate()
              }
            }}
            disabled={!workspaceId || retryPending}
            title={blockedByAI ? aiRequired.tooltip ?? undefined : undefined}
          >
            {retryPending ? 'Retrying…' : 'Retry'}
          </PrimaryButton>
          <span className="ml-auto" />
          <ErrorButton icon="block" kbd="X" onClick={onRejectStart}>
            Reject
          </ErrorButton>
        </div>
        {retryError != null && !retryPending && (
          <FooterActionError error={retryError} />
        )}
      </div>
    )
  }

  if (stage === 'pr_ready' || stage === 'pr_awaiting_val') {
    // ``Mark as fixed`` is the manual sign-off when the user has merged
    // the PR on GitHub. Flips status='validated' so the derivation moves
    // the row to section='done', stage='fixed'. Future work: detect the
    // merge automatically (poll the PR or webhook) and fire the
    // ``validation_checker`` agent so the verdict is grounded in a fresh
    // scan instead of trusting the user.
    return (
      <div className="flex items-center gap-2 w-full">
        <PrimaryButton
          icon="check_circle"
          kbd="F"
          title="Click after you've merged the PR on GitHub"
          onClick={() => {
            updateFinding.mutate({
              id: finding.id,
              data: { status: 'validated' },
            })
          }}
          disabled={updateFinding.isPending}
        >
          {updateFinding.isPending ? 'Marking…' : 'Mark as fixed'}
        </PrimaryButton>
        {prUrl && (
          <a
            href={prUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[12px] font-semibold rounded-lg bg-surface-container-lowest text-on-surface hover:bg-surface-container"
            style={{ border: '1px solid var(--outline-variant)' }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
              open_in_new
            </span>
            Open PR
          </a>
        )}
        <span className="ml-auto" />
        {/* "Close PR" would close-without-merge — needs a gh API call and
            a confirmation flow. Out of scope for this round; ship as a
            text button so the affordance is gone until it actually works. */}
      </div>
    )
  }

  // done variants
  return (
    <div className="w-full">
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className="material-symbols-outlined text-tertiary"
          style={{ fontSize: 14, fontVariationSettings: "'FILL' 1" }}
          aria-hidden
        >
          check_circle
        </span>
        <span className="text-[12px] font-semibold text-on-surface">Closed</span>
        <TextButton
          icon="undo"
          className="ml-auto"
          onClick={() => {
            updateFinding.mutate({
              id: finding.id,
              data: {
                status: 'in_progress',
                exception_reason: null,
                exception_note: null,
              },
            })
          }}
          disabled={updateFinding.isPending}
        >
          Reopen
        </TextButton>
      </div>
      <div
        className="rounded-full overflow-hidden"
        style={{ height: 3, background: 'var(--outline-variant)' }}
      >
        <div style={{ width: '100%', height: '100%', background: 'var(--tertiary)' }} />
      </div>
    </div>
  )
}

function RejectFooter({
  finding,
  onCancel,
  onRejected,
}: {
  finding: Finding
  onCancel: () => void
  onRejected: () => void
}) {
  const [reason, setReason] = useState<ExceptionReason | null>(null)
  const reject = useRejectFinding()

  const submit = () => {
    if (!reason) return
    reject.mutate(
      { id: finding.id, payload: { reason } },
      { onSuccess: () => onRejected() },
    )
  }

  return (
    <div className="flex items-center gap-2 w-full overflow-x-auto">
      <span className="text-[11.5px] uppercase tracking-wider text-on-surface-variant font-bold whitespace-nowrap mr-1">
        Reason
      </span>
      {REASON_OPTIONS.map((opt) => (
        <IssueFilterChip
          key={opt.value}
          active={reason === opt.value}
          onClick={() => setReason(opt.value)}
        >
          {opt.label}
        </IssueFilterChip>
      ))}
      <span className="ml-auto" />
      <TextButton onClick={onCancel}>Cancel</TextButton>
      <ErrorButton icon="block" onClick={submit} disabled={!reason || reject.isPending}>
        Reject
      </ErrorButton>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Permission prompt — the agent-permission approval gate footer. Renders
// when the latest remediation_executor run is parked on an ask-tier tool
// request (rm, git reset --hard, …) and the persisted ``permission_request``
// is loaded. Approve resumes the agent; Deny ends the run cleanly and the
// row falls through to the existing ``failed`` stage with a Retry CTA.
// ---------------------------------------------------------------------------

function PermissionPrompt({
  tool,
  patterns,
  pending,
  errorMessage,
  onApprove,
  onDeny,
}: {
  tool: string
  patterns: string[]
  pending: boolean
  errorMessage: string | null
  onApprove: () => void
  onDeny: () => void
}) {
  // "The pause" — editorial treatment of the destructive-action gate.
  // Three vertical bands: eyebrow (we're paused), command (the hero — what
  // will actually run), actions (the decision). The command sits in a
  // tonally-recessed surface with a 2px amber rule down the left edge,
  // because the entire purpose of this moment is to make the user read
  // the command before clicking — so the command itself is the visual
  // centerpiece, not chrome. Wraps cleanly for long branch names / paths
  // / multi-command shell strings (a previous fix replaced ``truncate``
  // with ``break-all whitespace-pre-wrap``; that contract holds here too).
  const detail = patterns.join(' ') || '(no detail)'
  return (
    <div
      className="flex flex-col w-full"
      data-testid="permission-prompt"
      style={{
        gap: 12,
        paddingTop: 14,
        paddingBottom: 14,
      }}
    >
      {/* Eyebrow row: amber pause chip on the left, tool name as a quiet
          mono tag on the right. Reads as "we paused — here's the surface
          we paused on" without competing with the command below. */}
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center gap-1.5 rounded-full"
          style={{
            padding: '3px 9px 3px 7px',
            background: 'var(--cd-amber-soft)',
            color: 'var(--cd-amber)',
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 13, fontVariationSettings: "'FILL' 1" }}
            aria-hidden
          >
            pause_circle
          </span>
          <span
            className="font-semibold uppercase"
            style={{
              fontSize: 10,
              letterSpacing: '0.14em',
              lineHeight: 1,
            }}
          >
            Awaiting your call
          </span>
        </span>
        <span
          className="ml-auto font-mono"
          style={{
            fontSize: 10.5,
            color: 'var(--cd-fg-4)',
            letterSpacing: '0.06em',
          }}
        >
          {tool}
        </span>
      </div>

      {/* The command — the hero. Code-block treatment with a left
          amber rail. The ``$`` prefix sits in a faint color so the
          actual command reads at full weight. */}
      <div
        className="relative overflow-hidden permission-cmd-enter"
        data-testid="permission-prompt-detail"
        style={{
          background: 'var(--cd-bg)',
          borderRadius: 'var(--cd-r-2)',
        }}
      >
        <span
          aria-hidden
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            bottom: 0,
            width: 2,
            background: 'var(--cd-amber)',
            opacity: 0.55,
          }}
        />
        <pre
          className="font-mono"
          style={{
            margin: 0,
            paddingTop: 10,
            paddingBottom: 10,
            paddingLeft: 14,
            paddingRight: 12,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: 'var(--cd-fg-1)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          <span style={{ color: 'var(--cd-fg-4)', userSelect: 'none' }}>$ </span>
          {detail}
        </pre>
      </div>

      {/* Actions, right-aligned. The eye reaches them last, after
          reading the command — that's the right order of operations. */}
      <div className="flex items-center gap-2 justify-end">
        <button
          type="button"
          onClick={onDeny}
          disabled={pending}
          data-testid="permission-deny"
          className="cd-btn cd-btn--ghost cd-btn--sm"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14 }}
            aria-hidden
          >
            block
          </span>
          Deny
          <KbdHint label="X" />
        </button>
        <button
          type="button"
          onClick={onApprove}
          disabled={pending}
          data-testid="permission-approve"
          className="cd-btn cd-btn--primary cd-btn--sm"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14 }}
            aria-hidden
          >
            {pending ? 'progress_activity' : 'check_circle'}
          </span>
          {pending ? 'Working…' : 'Approve'}
          <KbdHint label="A" />
        </button>
      </div>

      {errorMessage && (
        <div
          role="alert"
          data-testid="permission-error"
          style={{
            fontSize: 11,
            color: 'var(--cd-red)',
            padding: '6px 10px',
            background: 'var(--cd-red-soft)',
            borderRadius: 'var(--cd-r-2)',
          }}
        >
          {errorMessage}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tiny button primitives — kept inline since they're only used here.
// ---------------------------------------------------------------------------

interface BtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: string
  kbd?: string
  children: React.ReactNode
}

/**
 * Side-panel footer button primitives — Cyberdeck variants of the
 * cd-btn family so the panel speaks the same button language as the
 * rest of the chrome. Per critique round 2: one button pattern in
 * the footer, kbd-hint chip sits inside the button.
 */
function PrimaryButton({ icon, kbd, children, className, ...rest }: BtnProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`cd-btn cd-btn--primary cd-btn--sm ${className ?? ''}`}
    >
      {icon && (
        <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
          {icon}
        </span>
      )}
      {children}
      {kbd && <KbdHint label={kbd} />}
    </button>
  )
}

function TextButton({ icon, kbd, children, className, ...rest }: BtnProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`cd-btn cd-btn--ghost cd-btn--sm ${className ?? ''}`}
    >
      {icon && (
        <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
          {icon}
        </span>
      )}
      {children}
      {kbd && <KbdHint label={kbd} />}
    </button>
  )
}

function ErrorButton({ icon, kbd, children, className, ...rest }: BtnProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`cd-btn cd-btn--danger cd-btn--sm ${className ?? ''}`}
    >
      {icon && (
        <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>
          {icon}
        </span>
      )}
      {children}
      {kbd && <KbdHint label={kbd} />}
    </button>
  )
}

function KbdHint({ label }: { label: string }) {
  return (
    <kbd
      className="cd-key"
      aria-hidden
      style={{ marginLeft: 4 }}
    >
      {label}
    </kbd>
  )
}
