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
  useDashboard,
  useFixPostureCheck,
  useMarkSummarySeen,
  useRunAssessment,
} from '@/api/dashboard'
import type {
  DashboardPayload,
  PostureFixableCheck,
  PostureFixParams,
} from '@/api/dashboard'
import { onboardingApi } from '@/api/onboarding'
import AssessmentInProgressView from '@/components/dashboard/AssessmentInProgressView'
import AssessmentSummary from '@/components/dashboard/AssessmentSummary'
import IssueGradeHero, {
  type GradeLetter,
} from '@/components/dashboard/IssueGradeHero'
import IssueGradeHistoryChart from '@/components/dashboard/IssueGradeHistoryChart'
import IssueMetricCard from '@/components/dashboard/IssueMetricCard'
import IssueNeedsYouLine from '@/components/dashboard/IssueNeedsYouLine'
import PostureCard, {
  type PostureFeedback,
} from '@/components/dashboard/PostureCard'
import CompletionCelebration from '@/components/completion/CompletionCelebration'
import SummaryActionPanel from '@/components/completion/SummaryActionPanel'
import ErrorBoundary from '@/components/ErrorBoundary'
import ErrorState from '@/components/ErrorState'
import PageShell from '@/components/PageShell'
import PageSpinner from '@/components/PageSpinner'

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
  const disabled = running || mutation.isPending || !repoUrl

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
      disabled={disabled}
      onClick={() => {
        if (!repoUrl) return
        mutation.mutate(repoUrl, {
          onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          },
        })
      }}
      className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      aria-busy={mutation.isPending}
      aria-label={label}
    >
      {icon}
      {label}
    </button>
  )
}

function RunningDashboard({ data }: { data: DashboardPayload }) {
  const repoName = repoNameFromUrl(data.assessment?.repo_url)
  const headline = data.assessment?.completed_at
    ? 'Re-assessing your repository'
    : 'Assessment in progress'
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
        <AssessmentInProgressView
          assessmentId={data.assessment.id}
          headline={headline}
          startedAt={data.assessment.started_at ?? null}
        />
      )}
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
  const [postureFeedback, setPostureFeedback] = useState<PostureFeedback | null>(
    null,
  )
  // Live agent runs keyed by check_name so the inline strip can poll status.
  // Keeps the PostureCard stateless — we thread the workspace_id into the row.
  const [activeWorkspaceIds, setActiveWorkspaceIds] = useState<
    Partial<Record<PostureFixableCheck, string>>
  >({})

  const repoName = repoNameFromUrl(data.assessment?.repo_url)

  const handleGenerate = (
    checkName: PostureFixableCheck,
    params?: PostureFixParams,
  ) => {
    setPostureFeedback(null)
    fixMutation.mutate({ checkName, params }, {
      onSuccess: (resp) => {
        setActiveWorkspaceIds((prev) => ({
          ...prev,
          [checkName]: resp.workspace_id,
        }))
        setPostureFeedback({
          kind: 'success',
          checkName,
          message:
            `Agent workspace ${resp.workspace_id} is running — we'll update the ` +
            'row below when the draft PR opens.',
        })
      },
      onError: (err) => {
        const msg = err instanceof Error ? err.message : 'Unknown error'
        setPostureFeedback({
          kind: 'error',
          checkName,
          message: msg.includes('No repo registered')
            ? 'Run an assessment first — we need a repo to open the PR against.'
            : msg.includes('vault') || msg.includes('token')
              ? 'GitHub integration not configured. Open Settings to add a PAT.'
              : msg,
        })
      },
    })
  }

  // Only celebrate at grade A with a live completion row. The backend already
  // suppresses stale completion_ids when the current snapshot no longer meets
  // every criterion; this guard is defence in depth against a stale payload.
  const completionBlock =
    data.completion_id && data.grade === 'A'
      ? renderCompletionBlock(data, repoName, 'A')
      : null

  const grade = (data.grade ?? null) as GradeLetter | null
  const heroLabel = heroLabelFromGrade(grade)
  const heroCaption = heroCopyFromState(data)

  const openIssues = data.open_issues
  const timeToClose = data.time_to_close
  const needsYou = data.needs_you ?? {
    plans_waiting: 0,
    prs_ready: 0,
    critical_todo: 0,
  }

  return (
    <PageShell
      title="Overview"
      subtitle={repoName}
      actions={
        <RunAssessmentButton
          repoUrl={data.assessment?.repo_url ?? null}
          running={false}
          variant="rerun"
        />
      }
    >
      {completionBlock}
      <div className="flex flex-col gap-4">
        <IssueGradeHero
          letter={grade}
          label={heroLabel}
          caption={heroCaption}
          onOpenReview={() => navigate('/issues?section=review')}
          onViewRubric={() => navigate('/findings')}
        />

        <IssueNeedsYouLine
          plansWaiting={needsYou.plans_waiting ?? 0}
          prsReady={needsYou.prs_ready ?? 0}
          criticalTodo={needsYou.critical_todo ?? 0}
          onOpenReview={() => navigate('/issues?section=review')}
        />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <IssueMetricCard
            label="Open issues"
            value={String(openIssues?.current ?? 0)}
            deltaPct={openIssues?.delta_pct_30d ?? 0}
            lowerIsBetter
            series={openIssues?.history ?? []}
            footnote={openIssuesFootnote(data)}
          />
          <IssueMetricCard
            label="Time to close"
            value={formatDurationShort(timeToClose?.current_seconds ?? null)}
            deltaPct={timeToClose?.delta_pct_30d ?? 0}
            lowerIsBetter
            series={timeToClose?.history ?? []}
            accent="tertiary"
          />
        </div>

        <section
          data-testid="issue-grade-history-section"
          className="rounded-2xl"
          style={{
            background: 'var(--surface-container-lowest, #ffffff)',
            border: '1px solid var(--outline-variant, #abb3b7)',
          }}
        >
          <header className="flex items-center justify-between px-6 pt-5 pb-3 flex-wrap gap-3">
            <div>
              <h2 className="font-headline font-extrabold text-[18px] text-on-surface">
                Open issues over time
              </h2>
              <p className="text-[12px] text-on-surface-variant mt-0.5">
                Stacked by severity. The dotted line marks the most recent
                grade change.
              </p>
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              {[
                { label: 'Critical', color: 'var(--error, #9e3f4e)' },
                { label: 'High', color: 'rgb(199,128,52)' },
                { label: 'Medium', color: 'var(--secondary, #595e78)' },
                { label: 'Low', color: 'var(--tertiary, #575e78)' },
              ].map((l) => (
                <span
                  key={l.label}
                  className="inline-flex items-center gap-1.5 text-on-surface-variant"
                >
                  <span
                    className="rounded-sm"
                    style={{ width: 10, height: 10, background: l.color }}
                  />
                  {l.label}
                </span>
              ))}
            </div>
          </header>
          <div className="px-3 pb-4">
            <IssueGradeHistoryChart
              severityHistory={data.severity_history ?? null}
              gradeHistory={data.grade_history ?? []}
            />
          </div>
        </section>

        <PostureCard
          data={data}
          onGenerate={handleGenerate}
          pending={fixMutation.isPending}
          feedback={postureFeedback}
          activeWorkspaceIds={activeWorkspaceIds}
        />
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

function openIssuesFootnote(data: DashboardPayload): string | undefined {
  const counts = data.vulnerabilities?.by_severity
  if (!counts) return undefined
  const segments: string[] = []
  const order: Array<['critical' | 'high' | 'medium' | 'low', string]> = [
    ['critical', 'Critical'],
    ['high', 'High'],
    ['medium', 'Medium'],
    ['low', 'Low'],
  ]
  order.forEach(([key, label]) => {
    const v = counts[key] ?? 0
    if (v > 0) segments.push(`${v} ${label}`)
  })
  return segments.length > 0 ? segments.join(' · ') : undefined
}

function formatDurationShort(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  const totalMinutes = Math.round(seconds / 60)
  if (totalMinutes < 60) return `${totalMinutes}m`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours < 24) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  const remHours = hours % 24
  return remHours > 0 ? `${days}d ${remHours}h` : `${days}d`
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

  const summaryText = `I secured ${repoName} with OpenSec — ${vulnsFixed} vulnerabilities reviewed, ${posturePassing} posture checks passing, grade ${grade}. opensec.dev`
  const summaryMarkdown = `![Secured by OpenSec](opensec-summary.png)\n<!-- ${repoName} · completed ${completedDate} · grade ${grade} -->`

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
  return `${safe}_opensec-summary_${date}.png`
}
