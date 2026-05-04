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
import CompletionProgressCard from '@/components/dashboard/CompletionProgressCard'
import GradeRing from '@/components/dashboard/GradeRing'
import PostureCard, {
  type PostureFeedback,
} from '@/components/dashboard/PostureCard'
import ScannedByLine from '@/components/dashboard/ScannedByLine'
import ScorecardInfoLine from '@/components/dashboard/ScorecardInfoLine'
import CompletionCelebration from '@/components/completion/CompletionCelebration'
import CompletionStatusCard from '@/components/completion/CompletionStatusCard'
import SummaryActionPanel from '@/components/completion/SummaryActionPanel'
import ErrorBoundary from '@/components/ErrorBoundary'
import ErrorState from '@/components/ErrorState'
import PageShell from '@/components/PageShell'
import PageSpinner from '@/components/PageSpinner'

// PRD-0003 v0.2 expands the grade from 5 to 10 criteria. The labeled list
// comes from /api/dashboard.criteria; this constant is the gate for the
// "all met" celebration check.
const CRITERIA_TOTAL = 10

const SEVERITY_ORDER: Array<{
  key: 'critical' | 'high' | 'medium' | 'low'
  label: string
  tone: string
}> = [
  { key: 'critical', label: 'Critical', tone: 'text-error' },
  { key: 'high', label: 'High', tone: 'text-error' },
  // ADR-0029 / IMPL-0004 T14: medium severity reads as "fine" under the
  // tertiary (green) token. Swap to the new warning family so it scans as
  // "attention needed but not blocking".
  { key: 'medium', label: 'Medium', tone: 'text-warning' },
  { key: 'low', label: 'Low', tone: 'text-on-surface-variant' },
]

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
  // v0.2 dashboard: data.criteria is the labeled list per ADR-0032 — count
  // ``met`` entries directly. The legacy ``countCriteriaMet`` over
  // ``criteria_snapshot`` returns at most 5 (the PRD-0002 shape) but the UI
  // displays it against ``CRITERIA_TOTAL = 10``, producing the misleading
  // "4 of 10" the user reported. Match the AssessmentSummaryGate path
  // which uses the labeled list as the v0.2 source of truth.
  const criteriaMet =
    (data.criteria ?? []).filter((c) => c.met).length
  const remaining = Math.max(0, CRITERIA_TOTAL - criteriaMet)

  const heroCopy = buildHeroCopy(data.grade, remaining)

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

  const totalFindings = Object.values(data.findings_count_by_priority ?? {}).reduce(
    (a, b) => a + b,
    0,
  )
  const postureFails =
    (data.posture_total_count ?? 0) - (data.posture_pass_count ?? 0)
  const showGradeExplainer =
    data.grade !== 'A' && (totalFindings > 0 || postureFails > 0)

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
      {showGradeExplainer && (
        <GradeExplainer
          grade={data.grade}
          findingsCount={totalFindings}
          posturePassing={data.posture_pass_count ?? 0}
          postureTotal={data.posture_total_count ?? 0}
          onStartFixing={() => navigate('/findings')}
        />
      )}
      <div className="flex flex-col gap-6">
        <section className="flex flex-col items-start gap-6 rounded-3xl bg-surface-container-low p-8 md:flex-row md:items-center">
          <GradeRing
            grade={data.grade}
            criteriaMet={criteriaMet}
            criteriaTotal={CRITERIA_TOTAL}
          />
          <div className="flex-1">
            <p className="text-xs font-medium uppercase tracking-wide text-on-surface-variant">
              Security grade
            </p>
            <h2 className="mt-1 font-headline text-3xl font-bold text-on-surface">
              {heroCopy.headline}
            </h2>
            <p className="mt-2 text-base text-on-surface-variant">
              {heroCopy.body}
            </p>
          </div>
          {data.completion_id && (
            <div className="w-full md:w-auto md:max-w-xs md:flex-shrink-0">
              <CompletionStatusCard
                completionId={data.completion_id}
                completedAt={data.assessment?.completed_at ?? null}
              />
            </div>
          )}
        </section>

        {/* PR-B: Scanned-by row sits directly under the hero so the brand
            trust signal (Trivy 0.52 · 7 findings · ...) lands every time
            the report card renders. */}
        {data.tools && data.tools.length > 0 && (
          <ScannedByLine tools={data.tools} />
        )}

        <CompletionProgressCard
          criteriaMet={criteriaMet}
          criteriaTotal={CRITERIA_TOTAL}
          repoName={repoName}
        />

        <VulnerabilitiesCard
          data={data}
          onStartFixing={() => navigate('/findings')}
        />
        <PostureCard
          data={data}
          onGenerate={handleGenerate}
          pending={fixMutation.isPending}
          feedback={postureFeedback}
          activeWorkspaceIds={activeWorkspaceIds}
        />

        <ScorecardInfoLine />
      </div>
    </PageShell>
  )
}

function VulnerabilitiesCard({
  data,
  onStartFixing,
}: {
  data: DashboardPayload
  onStartFixing: () => void
}) {
  const counts = data.findings_count_by_priority ?? {}
  const total = SEVERITY_ORDER.reduce(
    (sum, s) => sum + (counts[s.key] ?? 0),
    0,
  )
  const hasIssues = total > 0

  return (
    <section className="flex flex-col gap-4 rounded-3xl bg-surface-container-low p-6">
      <header>
        <h3 className="font-headline text-lg font-bold text-on-surface">
          Vulnerabilities
        </h3>
        <p className="text-sm text-on-surface-variant">
          Findings waiting to be solved.
        </p>
      </header>

      <div className="grid grid-cols-4 gap-3">
        {SEVERITY_ORDER.map((sev) => {
          const value = counts[sev.key] ?? 0
          return (
            <div
              key={sev.key}
              className="rounded-2xl bg-surface-container p-3"
            >
              <p className={`text-2xl font-bold leading-none ${sev.tone}`}>
                {value}
              </p>
              <p className="mt-1 text-xs font-medium text-on-surface-variant">
                {sev.label}
              </p>
            </div>
          )
        })}
      </div>

      {hasIssues ? (
        <button
          type="button"
          onClick={onStartFixing}
          className="inline-flex w-max items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden>
            play_arrow
          </span>
          Start fixing
        </button>
      ) : (
        <p className="text-sm text-tertiary">No open vulnerabilities. Nice.</p>
      )}
    </section>
  )
}


function GradeExplainer({
  grade,
  findingsCount,
  posturePassing,
  postureTotal,
  onStartFixing,
}: {
  grade: DashboardPayload['grade']
  findingsCount: number
  posturePassing: number
  postureTotal: number
  onStartFixing: () => void
}) {
  const postureFails = Math.max(0, postureTotal - posturePassing)
  const parts: string[] = []
  if (findingsCount > 0) {
    parts.push(
      `${findingsCount} ${findingsCount === 1 ? 'vulnerability' : 'vulnerabilities'}`,
    )
  }
  if (postureFails > 0) {
    parts.push(
      `${postureFails} of ${postureTotal} posture check${postureTotal === 1 ? '' : 's'} failing`,
    )
  }
  const summary = parts.join(' and ')

  return (
    <section
      data-testid="grade-explainer"
      className="mb-6 rounded-3xl bg-surface-container-low p-6"
    >
      <div className="flex items-start gap-4">
        <span
          className="material-symbols-outlined text-tertiary mt-0.5"
          aria-hidden
        >
          info
        </span>
        <div className="flex-1">
          <h3 className="font-headline text-lg font-bold text-on-surface">
            {grade === 'F'
              ? 'Your project starts at grade F'
              : `Your project is at grade ${grade}`}
          </h3>
          <p className="mt-1 text-sm text-on-surface-variant">
            {summary
              ? `We found ${summary}. Each fix moves the grade up — start anywhere below.`
              : 'Keep fixing findings to raise the grade.'}
          </p>
          {findingsCount > 0 && (
            <button
              type="button"
              onClick={onStartFixing}
              className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90"
            >
              <span className="material-symbols-outlined text-sm" aria-hidden>
                play_arrow
              </span>
              Start fixing
            </button>
          )}
        </div>
      </div>
    </section>
  )
}

function buildHeroCopy(
  grade: DashboardPayload['grade'],
  remaining: number,
): { headline: string; body: string } {
  if (grade == null) {
    return {
      headline: 'Working on it',
      body: 'We are still assessing your repository.',
    }
  }
  if (grade === 'A') {
    return {
      headline: 'Security completion reached',
      body: 'All five criteria are met. Keep it up.',
    }
  }
  if (grade === 'F' || grade === 'D') {
    return {
      headline: 'Work to do',
      body: `Start with any failing check below. Fix ${remaining} item${remaining === 1 ? '' : 's'} to reach security completion.`,
    }
  }
  if (remaining === 0) {
    return {
      headline: 'Almost there',
      body: 'Criteria look good. Address any remaining findings to earn grade A.',
    }
  }
  return {
    headline: 'Nearly there',
    body: `Fix ${remaining} more ${remaining === 1 ? 'item' : 'items'} to reach security completion.`,
  }
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
