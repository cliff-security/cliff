/**
 * DashboardPage — the report-card home (frame 2.2).
 *
 * IMPL-0002 Milestone G4. Switches between assessment-running and
 * report-card states based on the /api/dashboard payload. Imports
 * CompletionStatusCard as a Session-F-owned stub (renders its props;
 * internals land in Session F).
 */

import type React from 'react'
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import {
  useAssessmentStatus,
  useDashboard,
  useFixPostureCheck,
  useMarkSummarySeen,
  useRunAssessment,
} from '@/api/dashboard'
import type { DashboardPayload, PostureFixableCheck } from '@/api/dashboard'
import {
  AutoDetectBanner,
  useOpenAIProvider,
} from '@/components/ai-provider'
import { useAIRequired } from '@/api/aiProvider'
import { onboardingApi } from '@/api/onboarding'
import AssessmentFailedCard, {
  type AssessmentFailedStep as FailedStepLabel,
} from '@/components/dashboard/AssessmentFailedCard'
import AssessmentRunningCard from '@/components/dashboard/AssessmentRunningCard'
import AssessmentSummary from '@/components/dashboard/AssessmentSummary'
import IssueGradeHero, {
  type GradeLetter,
} from '@/components/dashboard/IssueGradeHero'
import LastAssessmentPanel from '@/components/dashboard/LastAssessmentPanel'
import LevelUpPanel from '@/components/dashboard/LevelUpPanel'
import OpenBySeverityCard from '@/components/dashboard/OpenBySeverityCard'
import PreviousAssessmentCard from '@/components/dashboard/PreviousAssessmentCard'
import CompletionCelebration from '@/components/completion/CompletionCelebration'
import SummaryActionPanel from '@/components/completion/SummaryActionPanel'
import ErrorBoundary from '@/components/ErrorBoundary'
import ErrorState from '@/components/ErrorState'
import PageShell from '@/components/PageShell'
import PageSpinner from '@/components/PageSpinner'
import PostOnboardingCurtain from '@/components/PostOnboardingCurtain'

// PRD-0003 v0.2 expands the grade from 5 to 10 criteria. The labeled list
// comes from /api/dashboard.criteria; this constant is the gate for the
// "all met" celebration check.
const CRITERIA_TOTAL = 10

export default function DashboardPage() {
  return (
    <ErrorBoundary
      fallbackTitle="Dashboard error"
      fallbackSubtitle="Something went wrong loading the dashboard."
    >
      {/* One-time hand-off animation between onboarding and the
       *  dashboard. Self-clearing; renders nothing after the first
       *  ~1.2s post-onboarding or on every other navigation. */}
      <PostOnboardingCurtain />
      <DashboardContent />
    </ErrorBoundary>
  )
}

function DashboardContent() {
  const { data, isLoading, isError, refetch } = useDashboard()
  useAckOnboardingOnce(data)

  if (isError) {
    return (
      <PageShell title="Overview">
        <ErrorState
          title="Couldn't load the dashboard"
          subtitle="Please try again."
          onRetry={() => refetch()}
        />
      </PageShell>
    )
  }

  if (isLoading || !data) {
    return (
      <PageShell title="Overview">
        <PageSpinner />
      </PageShell>
    )
  }

  if (data.assessment?.status === 'running' || data.assessment?.status === 'pending') {
    return <RunningDashboard data={data} />
  }

  if (data.assessment?.status === 'failed') {
    return <FailedDashboard data={data} />
  }

  if (data.assessment == null) {
    return <EmptyDashboard />
  }

  // Assessment-complete interstitial (PRD-0003 v0.2 Surface 3 / ADR-0032 §4):
  // show once after the first completed assessment, gated server-side via
  // ``summary_seen_at``. Clicking the CTA fires ``markSummarySeen`` and
  // invalidates the dashboard query so the next render falls through to
  // the report card.
  if (
    data.assessment.status === 'complete'
    && data.assessment.summary_seen_at == null
  ) {
    return <AssessmentSummaryGate data={data} />
  }

  return <ReportCard data={data} />
}

function AssessmentSummaryGate({ data }: { data: DashboardPayload }) {
  const queryClient = useQueryClient()
  const mutation = useMarkSummarySeen()
  const a = data.assessment!
  const grade = data.grade ?? 'F'
  // The labeled ``criteria`` list is the v0.2 source of truth for "met"
  // — count the entries flagged as met.
  const criteriaMet =
    (data.criteria ?? []).filter((c) => c.met).length
  const vulnsTotal = data.vulnerabilities?.total ?? 0
  const postureFailing = (data.posture_total_count ?? 0) - (data.posture_pass_count ?? 0)
  return (
    <PageShell title="Overview">
      <AssessmentSummary
        grade={grade}
        criteriaMet={criteriaMet}
        criteriaTotal={CRITERIA_TOTAL}
        stats={{
          vulnerabilitiesTotal: vulnsTotal,
          postureFailing: Math.max(postureFailing, 0),
          posturePassing: data.posture_pass_count ?? 0,
          postureTotal: data.posture_total_count ?? 0,
          quickWins: 0,
        }}
        onViewReportCard={() =>
          mutation.mutate(a.id, {
            onSuccess: () => {
              queryClient.invalidateQueries({ queryKey: ['dashboard'] })
            },
          })
        }
        pending={mutation.isPending}
      />
    </PageShell>
  )
}

/**
 * Primary action in the dashboard header — "Run assessment" / "Re-run
 * assessment" (PRD-0004 Story 1 / IMPL-0004 T8).
 *
 * Variants:
 *   - first-run: labelled "Run assessment", surfaced on EmptyDashboard too
 *   - subsequent: labelled "Re-run assessment", sits top-right of ReportCard
 *   - running/pending: disabled, label "Assessment running"
 *   - submitting: disabled with inline spinner, label "Starting…"
 */
function RunAssessmentButton({
  repoUrl,
  running,
  variant,
}: {
  repoUrl: string | null
  running: boolean
  variant: 'first-run' | 'rerun'
}) {
  const mutation = useRunAssessment()
  const queryClient = useQueryClient()
  const aiRequired = useAIRequired()
  const { open: openAIProvider } = useOpenAIProvider()
  const blockedByAI = !aiRequired.enabled && !aiRequired.loading
  const disabled =
    running || mutation.isPending || !repoUrl || blockedByAI

  let label: string
  if (mutation.isPending) {
    label = 'Starting…'
  } else if (running) {
    label = 'Assessment running'
  } else if (variant === 'first-run') {
    label = 'Run assessment'
  } else {
    label = 'Re-run assessment'
  }

  const icon = mutation.isPending ? (
    <span
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-on-primary/40 border-t-on-primary"
      aria-hidden
    />
  ) : (
    <span className="material-symbols-outlined text-sm" aria-hidden>
      refresh
    </span>
  )

  return (
    <button
      type="button"
      data-testid="run-assessment-button"
      data-variant={variant}
      // Clicks while disabled-due-to-missing-AI open the connect modal
      // so the user has a direct path forward.
      onClick={() => {
        if (blockedByAI) {
          openAIProvider()
          return
        }
        if (disabled || !repoUrl) return
        mutation.mutate(repoUrl, {
          onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          },
        })
      }}
      // When the only reason we'd be disabled is missing AI, keep the
      // button clickable (so the openAIProvider path fires) but render
      // the disabled visual + tooltip.
      disabled={disabled && !blockedByAI}
      title={blockedByAI ? aiRequired.tooltip ?? undefined : undefined}
      aria-disabled={disabled || blockedByAI}
      className="cd-btn cd-btn--primary cd-btn--sm"
      style={blockedByAI ? { opacity: 0.7 } : undefined}
      aria-busy={mutation.isPending}
      aria-label={label}
    >
      {icon}
      {label}
    </button>
  )
}

function RunningDashboard({ data }: { data: DashboardPayload }) {
  const navigate = useNavigate()
  const repoName = repoNameFromUrl(data.assessment?.repo_url)
  const assessmentId = data.assessment?.id ?? null
  const { data: status } = useAssessmentStatus(assessmentId)

  const tools = (status?.tools ?? []).map((t) => ({
    id: t.id,
    label: humanizeToolLabel(t.label, t.version),
    icon: t.icon,
    state: t.state,
    result: t.result,
  }))
  const steps = status?.steps ?? []
  const progressPct = status?.progress_pct ?? 0
  const previous = status?.previous_assessment ?? null

  return (
    <PageShell
      title="Overview"
      subtitle={repoName}
      actions={
        <RunAssessmentButton
          repoUrl={data.assessment?.repo_url ?? null}
          running
          variant="rerun"
        />
      }
    >
      {data.assessment && (
        <div className="cliff-fade-in">
          <AssessmentRunningCard
            repoUrl={data.assessment.repo_url ?? null}
            startedAt={data.assessment.started_at ?? null}
            progressPct={progressPct}
            steps={steps}
            tools={tools}
            onViewLiveLog={() => navigate('/settings/integrations')}
            onConfigureScanners={() => navigate('/settings/integrations')}
          />
          {previous && (
            <PreviousAssessmentCard
              info={{
                assessment_id: previous.assessment_id,
                grade: previous.grade,
                open_count: previous.open_count,
                commit_sha: previous.commit_sha,
                finished_at: previous.finished_at,
                report_href: previous.report_href,
              }}
            />
          )}
        </div>
      )}
    </PageShell>
  )
}

function humanizeToolLabel(label: string, version: string | null | undefined): string {
  // ``label`` already includes the version when the engine wrote one. When
  // the label is bare and we have a version, surface it inline.
  if (!version || version === 'unknown') return label
  if (label.includes(version)) return label
  return `${label} ${version}`
}

/**
 * Failed-state branch (migration 015 — failure surfacing). Reads the new
 * ``error_*`` fields from the dashboard payload (mirrored from the
 * assessment row) and renders the friendly headline + collapsible details
 * + one-click retry. Retry re-uses ``POST /assessment/run`` with the prior
 * ``repo_url`` — no new endpoint, no edit-URL flow.
 */
function FailedDashboard({ data }: { data: DashboardPayload }) {
  const a = data.assessment!
  const repoName = repoNameFromUrl(a.repo_url ?? null)
  const reassessMutation = useRunAssessment()
  const queryClient = useQueryClient()

  const failedStep = (a.failed_step as FailedStepLabel | null | undefined) ?? null
  const message =
    a.error_message ?? 'Something went wrong while running the assessment'
  const details = a.error_details ?? null

  const handleRetry = () => {
    const repoUrl = a.repo_url ?? null
    if (!repoUrl) return
    reassessMutation.mutate(repoUrl, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      },
    })
  }

  return (
    <PageShell
      title="Overview"
      subtitle={repoName}
      actions={
        <RunAssessmentButton
          repoUrl={a.repo_url ?? null}
          running={false}
          variant="rerun"
        />
      }
    >
      <div className="cliff-fade-in">
        <AssessmentFailedCard
          message={message}
          failedStep={failedStep}
          details={details}
          retrying={reassessMutation.isPending}
          onRetry={handleRetry}
        />
      </div>
    </PageShell>
  )
}

function EmptyDashboard() {
  return (
    <PageShell
      title="Overview"
      actions={
        <RunAssessmentButton
          repoUrl={null}
          running={false}
          variant="first-run"
        />
      }
    >
      <section
        data-testid="dashboard-empty"
        className="flex flex-col items-center gap-5 rounded-3xl bg-surface-container-low px-10 py-20 text-center"
      >
        <span
          className="material-symbols-outlined text-primary"
          style={{ fontSize: '44px' }}
          aria-hidden
        >
          radar
        </span>
        <div>
          <h2 className="font-headline text-2xl font-bold text-on-surface">
            No assessment yet
          </h2>
          <p className="mt-2 max-w-md text-sm text-on-surface-variant">
            Connect a repository to get your first security grade. It takes
            under a minute.
          </p>
        </div>
        <p className="text-xs text-on-surface-variant">
          Finish onboarding to connect a repository.
        </p>
      </section>
    </PageShell>
  )
}

/**
 * Fire ``POST /api/onboarding/complete`` exactly once, the first time the
 * dashboard sees the current assessment flip to ``complete``. This moves the
 * completion ack off the wizard (which used to block on a 409 → complete
 * transition, defeating the progress-list UX).
 */
function useAckOnboardingOnce(data: DashboardPayload | undefined): void {
  const ackedRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const assessment = data?.assessment
    if (!assessment || assessment.status !== 'complete') return
    if (ackedRef.current.has(assessment.id)) return
    ackedRef.current.add(assessment.id)
    onboardingApi
      .complete({ assessment_id: assessment.id })
      .catch(() => {
        // Already-complete onboarding is expected (idempotent); swallow.
      })
  }, [data?.assessment])
}

function ReportCard({ data }: { data: DashboardPayload }) {
  const navigate = useNavigate()
  const fixMutation = useFixPostureCheck()
  const reassessMutation = useRunAssessment()
  const queryClient = useQueryClient()
  const { open: openAIProvider } = useOpenAIProvider()

  const repoName = repoNameFromUrl(data.assessment?.repo_url)

  // Only celebrate at grade A with a live completion row. The backend already
  // suppresses stale completion_ids when the current snapshot no longer meets
  // every criterion; this guard is defence in depth against a stale payload.
  const completionBlock =
    data.completion_id && data.grade === 'A'
      ? renderCompletionBlock(data, repoName, 'A')
      : null

  const grade = (data.grade ?? null) as GradeLetter | null
  const heroLabel = data.grade_label ?? heroLabelFromGrade(grade)
  const heroCaption = data.grade_caption ?? heroCopyFromState(data)

  const openBySeverity = (data.open_by_severity ?? []) as Array<{
    kind: 'critical' | 'high' | 'medium' | 'low'
    count: number
    weekly_delta: number
  }>

  const [autoFixErrors, setAutoFixErrors] = useState<
    Record<string, string | null>
  >({})

  const handleAutoFix = async (checkNames: string[]) => {
    // Fan out parallel POST /api/posture/fix/{check_name}. The route's 409
    // guard ("already running") is a deliberate no-op; any other rejection
    // is something the user needs to see (Q01R B24). We use ``allSettled``
    // so one bad check doesn't cancel the others, then re-throw a combined
    // error if every call rejected — that re-throw is what ``GateRow``
    // catches and forwards to ``onAutoFixError``.
    const results = await Promise.allSettled(
      checkNames.map((name) =>
        fixMutation.mutateAsync({ checkName: name as PostureFixableCheck }),
      ),
    )
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })

    const rejections = results.flatMap((r, i) => {
      if (r.status !== 'rejected') return []
      const msg = r.reason instanceof Error ? r.reason.message : String(r.reason)
      // 409 with "workspace_already_running" is the deliberate no-op — skip it.
      if (msg.startsWith('409:') && msg.includes('workspace_already_running')) {
        return []
      }
      return [{ name: checkNames[i], reason: r.reason as unknown }]
    })

    if (rejections.length > 0) {
      // Re-throw the first real rejection so ``GateRow``'s onClickAction
      // ``catch`` fires and forwards a parsed message via ``onAutoFixError``.
      throw rejections[0].reason instanceof Error
        ? rejections[0].reason
        : new Error(String(rejections[0].reason))
    }
  }

  const handleAutoFixError = (gateId: string, message: string) => {
    setAutoFixErrors((prev) => ({ ...prev, [gateId]: message }))
  }

  const handleReassess = () => {
    const repoUrl = data.assessment?.repo_url ?? null
    if (!repoUrl) return
    reassessMutation.mutate(repoUrl, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      },
    })
  }

  const handleShareReport = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(window.location.href)
    }
  }

  return (
    <PageShell
      title="Overview"
      subtitle={repoName}
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="dashboard-share-report"
            onClick={handleShareReport}
            className="cd-btn cd-btn--ghost cd-btn--sm"
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 13 }}
              aria-hidden
            >
              share
            </span>
            Share report
          </button>
          <RunAssessmentButton
            repoUrl={data.assessment?.repo_url ?? null}
            running={false}
            variant="rerun"
          />
        </div>
      }
    >
      {completionBlock}
      <div className="flex flex-col gap-4">
        <div className="cliff-fade-in">
          <AutoDetectBanner onConfigureManually={openAIProvider} />
        </div>
        <div className="cliff-fade-in cd-stagger-1">
          <IssueGradeHero
            letter={grade}
            label={heroLabel}
            caption={heroCaption}
            onOpenReview={() => navigate('/issues?section=review')}
          />
        </div>

        <div className="grid gap-4 md:grid-cols-[380px_1fr] cliff-fade-in cd-stagger-2">
          <OpenBySeverityCard
            rows={openBySeverity}
            onSelectSeverity={(kind) => navigate(`/issues?severity=${kind}`)}
          />
          {data.level_up ? (
            <LevelUpPanel
              data={{
                current: data.level_up.current as 'A' | 'B' | 'C' | 'D' | 'F',
                next: (data.level_up.next ?? null) as
                  | 'A'
                  | 'B'
                  | 'C'
                  | 'D'
                  | 'F'
                  | null,
                summary: data.level_up.summary ?? '',
                gates: (data.level_up.gates ?? []).map((g) => ({
                  id: g.id,
                  label: g.label,
                  detail: g.detail,
                  current: g.current,
                  target: g.target,
                  unit: g.unit,
                  status: g.status,
                  action_label: g.action_label,
                  action_href: g.action_href,
                  auto_fixable_check_names: g.auto_fixable_check_names ?? [],
                })),
              }}
              onNavigate={(href) => navigate(href)}
              onAutoFix={handleAutoFix}
              onAutoFixError={handleAutoFixError}
              autoFixErrors={autoFixErrors}
              onViewRubric={() =>
                document
                  .querySelector<HTMLDialogElement>(
                    '[data-testid="issue-grade-hero-rubric-dialog"]',
                  )
                  ?.showModal?.()
              }
            />
          ) : (
            <section
              data-testid="level-up-empty"
              className="rounded-2xl border border-outline-variant p-6 flex items-center justify-center text-on-surface-variant text-[13px]"
              style={{ background: 'var(--surface-container-lowest, #ffffff)' }}
            >
              No grade yet — run an assessment to see your path forward.
            </section>
          )}
        </div>

        {data.last_assessment ? (
          <div className="cliff-fade-in cd-stagger-3">
            <LastAssessmentPanel
              data={{
                repo_url: data.last_assessment.repo_url ?? data.assessment?.repo_url ?? '',
                finished_at: data.last_assessment.finished_at,
                duration_ms: data.last_assessment.duration_ms,
                commit_sha: data.last_assessment.commit_sha,
                branch: data.last_assessment.branch,
                scanned_files: data.last_assessment.scanned_files,
                scanned_deps: data.last_assessment.scanned_deps,
                scanners: (data.last_assessment.scanners ?? []) as Array<{
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
                }>,
              }}
              onReassess={handleReassess}
              reassessing={reassessMutation.isPending}
            />
          </div>
        ) : null}
      </div>
    </PageShell>
  )
}

// ----------------------------------------------------------- hero copy helpers

function heroLabelFromGrade(grade: GradeLetter | null): string {
  if (grade === null) return 'Awaiting first scan'
  if (grade === 'A') return 'Stable'
  if (grade === 'B') return 'Steady'
  if (grade === 'C' || grade === 'D') return 'At risk'
  return 'Vulnerable'
}

function heroCopyFromState(data: DashboardPayload): string {
  const grade = data.grade
  if (grade == null) {
    return 'Run an assessment to earn your first grade. The Issues page surfaces every fix as a one-click Start.'
  }
  const open = data.open_issues
  const needs = data.needs_you
  const parts: string[] = []
  if (open && typeof open.delta_pct_30d === 'number' && open.delta_pct_30d !== 0) {
    const direction = open.delta_pct_30d < 0 ? 'down' : 'up'
    parts.push(
      `Open issues are ${direction} ${Math.abs(open.delta_pct_30d)}% over the last 30 days.`,
    )
  } else if (open) {
    parts.push(
      `${open.current ?? 0} ${open.current === 1 ? 'issue' : 'issues'} open right now.`,
    )
  }
  if (needs) {
    const waiting = (needs.plans_waiting ?? 0) + (needs.prs_ready ?? 0)
    if (waiting > 0) {
      parts.push(
        `${waiting} ${waiting === 1 ? 'item is' : 'items are'} waiting on you.`,
      )
    }
  }
  return parts.join(' ')
}

function repoNameFromUrl(url: string | null | undefined): string {
  if (!url) return 'your repository'
  try {
    const u = new URL(url)
    return u.pathname.replace(/^\//, '').replace(/\.git$/, '') || url
  } catch {
    return url
  }
}

type LetterGrade = 'A' | 'B' | 'C' | 'D' | 'F'

function renderCompletionBlock(
  data: DashboardPayload,
  repoName: string,
  grade: LetterGrade,
): React.ReactNode {
  const completionId = data.completion_id ?? ''
  const completedAtIso = data.assessment?.completed_at ?? null
  const completedDate = formatCompletedDate(completedAtIso)
  const vulnsFixed = Object.values(data.findings_count_by_priority ?? {}).reduce(
    (a, b) => a + b,
    0,
  )
  const posturePassing = data.posture_pass_count ?? 0
  const filename = buildSummaryFilename(repoName, completedAtIso)

  const summaryText = `I secured ${repoName} with Cliff — ${vulnsFixed} vulnerabilities reviewed, ${posturePassing} posture checks passing, grade ${grade}. cliff.dev`
  const summaryMarkdown = `![Secured by Cliff](cliff-summary.png)\n<!-- ${repoName} · completed ${completedDate} · grade ${grade} -->`

  const scrollToPanel = () => {
    document
      .getElementById('summary-panel')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="mb-8" data-testid="completion-block">
      <CompletionCelebration
        repoName={repoName}
        completedDate={completedDate}
        grade={grade}
        criteriaCount={CRITERIA_TOTAL}
        onDownloadClick={scrollToPanel}
        onCopyTextClick={() => {
          void navigator.clipboard?.writeText(summaryText)
        }}
        onCopyMarkdownClick={() => {
          void navigator.clipboard?.writeText(summaryMarkdown)
        }}
      />
      <div className="mt-10">
        <SummaryActionPanel
          completionId={completionId}
          summaryText={summaryText}
          summaryMarkdown={summaryMarkdown}
          filename={filename}
          cardProps={{
            repoName,
            completedAt: completedDate,
            vulnsFixed,
            postureChecksPassing: posturePassing,
            prsMerged: 0,
            grade,
          }}
        />
      </div>
    </div>
  )
}

function formatCompletedDate(iso: string | null): string {
  if (!iso) return 'today'
  // Defensive: backend emits full ISO; take the date part for display.
  return iso.slice(0, 10)
}

function buildSummaryFilename(repoName: string, iso: string | null): string {
  const safe = repoName.replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
  const date = (iso ?? new Date().toISOString()).slice(0, 10)
  return `${safe}_cliff-summary_${date}.png`
}
