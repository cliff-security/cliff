/**
 * DashboardPage — the report-card home (frame 2.2).
 *
 * IMPL-0002 Milestone G4. Switches between assessment-running and
 * report-card states based on the /api/dashboard payload. Imports
 * CompletionStatusCard as a Session-F-owned stub (renders its props;
 * internals land in Session F).
 */

import type React from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import {
  useDashboard,
  useFixPostureCheck,
  useMarkSummarySeen,
  usePostureFixStatus,
  useRunAssessment,
} from '@/api/dashboard'
import type {
  DashboardPayload,
  Finding,
  PostureCheckName,
  PostureCheckStatus,
  PostureFixableCheck,
  PostureFixParams,
} from '@/api/dashboard'
import { onboardingApi } from '@/api/onboarding'
import AssessmentInProgressView from '@/components/dashboard/AssessmentInProgressView'
import AssessmentSummary from '@/components/dashboard/AssessmentSummary'
import CompletionProgressCard from '@/components/dashboard/CompletionProgressCard'
import GradeRing from '@/components/dashboard/GradeRing'
import ScannedByLine from '@/components/dashboard/ScannedByLine'
import ScorecardInfoLine from '@/components/dashboard/ScorecardInfoLine'
import CompletionCelebration from '@/components/completion/CompletionCelebration'
import CompletionStatusCard from '@/components/completion/CompletionStatusCard'
import SummaryActionPanel from '@/components/completion/SummaryActionPanel'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'
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

interface PostureFeedback {
  kind: 'success' | 'error'
  checkName: PostureFixableCheck
  message: string
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

// Per-check metadata: label, what-it-checks blurb, and ordered fix steps.
// The two "auto-fix" checks (security_md, dependabot_config) show a
// primary "Generate and open PR" CTA *in addition* to the manual steps so
// maintainers can either let OpenSec do it or do it themselves.
const POSTURE_META: Record<
  PostureCheckName,
  {
    label: string
    failLabel: string
    description: string
    steps: string[]
    docHref?: string
    docLabel?: string
  }
> = {
  security_md: {
    label: 'SECURITY.md is committed',
    failLabel: 'SECURITY.md is missing',
    description:
      'A security policy tells researchers how to report vulnerabilities privately instead of filing a public issue.',
    steps: [
      'Create SECURITY.md at the repo root.',
      'Add a "Reporting a vulnerability" section with a contact email or private issue link.',
      'State your supported versions and expected response time (e.g. 72 hours).',
      'Commit and push to main — OpenSec re-detects on the next assessment.',
    ],
    docHref:
      'https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository',
    docLabel: 'GitHub: adding a security policy',
  },
  dependabot_config: {
    label: 'Dependabot is configured',
    failLabel: 'Dependabot is not configured',
    description:
      'Dependabot opens weekly PRs for outdated dependencies so you do not ship unpatched CVEs.',
    steps: [
      'Create .github/dependabot.yml at the repo root.',
      'Declare a package-ecosystem entry for each lockfile OpenSec detected.',
      'Set a weekly schedule and an optional reviewer team.',
      'Commit and merge — Dependabot runs automatically on GitHub-hosted repos.',
    ],
    docHref:
      'https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuring-dependabot-version-updates',
    docLabel: 'GitHub: Dependabot version updates',
  },
  branch_protection: {
    label: 'Default branch is protected',
    failLabel: 'Default branch is not protected',
    description:
      'Without branch protection, a compromised contributor or misclick can push straight to main with no review.',
    steps: [
      'Go to Settings → Branches → Add rule for main.',
      'Enable "Require a pull request before merging" with at least 1 reviewer.',
      'Enable "Require status checks to pass" and select your CI checks.',
      'Save the rule, then re-assess in OpenSec.',
    ],
    docHref:
      'https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches',
    docLabel: 'GitHub: about protected branches',
  },
  no_force_pushes: {
    label: 'Force pushes are blocked',
    failLabel: 'Force pushes to main are allowed',
    description:
      'Force-pushes rewrite history and can silently drop commits — critical on your default branch.',
    steps: [
      'Open the branch protection rule for main (Settings → Branches).',
      'Under "Rules applied to everyone including administrators", tick "Do not allow force pushes".',
      'Save and re-assess.',
    ],
    docHref:
      'https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#allow-force-pushes',
    docLabel: 'GitHub: force-push protections',
  },
  signed_commits: {
    label: 'Recent commits are signed',
    failLabel: 'Recent commits are unsigned (advisory)',
    description:
      'Signed commits prove each commit actually came from its claimed author. Advisory — we recommend it, but it does not block Grade A.',
    steps: [
      'Generate a GPG or SSH signing key and add it to your GitHub profile.',
      'Run "git config --global commit.gpgsign true" (or use "ssh" for SSH signing).',
      'Amend or re-commit from now on so new commits show a Verified badge.',
      'Optional: require signed commits in your branch protection rule.',
    ],
    docHref:
      'https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification',
    docLabel: 'GitHub: commit signature verification',
  },
  no_secrets_in_code: {
    label: 'No secrets detected in tracked files',
    failLabel: 'Possible secrets detected in tracked files',
    description:
      'OpenSec scans for high-specificity tokens: AWS AKIA keys, GitHub ghp_/ghs_, Stripe sk_live_, Google AIza, and PEM blocks.',
    steps: [
      'Open the "detail" payload for this check to see which files matched.',
      'Remove the secret from the file and rotate the credential immediately — assume it is leaked.',
      'Add the pattern to .gitignore if it was a config file that should never be tracked.',
      'For historical removal, consider "git filter-repo" or the BFG Repo-Cleaner, then force-push (careful).',
      'Add an entry to .opensec/secrets-ignore only after you are sure the match is a false positive.',
    ],
    docHref:
      'https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning',
    docLabel: 'GitHub: about secret scanning',
  },
  lockfile_present: {
    label: 'A dependency lockfile is committed',
    failLabel: 'No dependency lockfile detected',
    description:
      'Lockfiles pin exact versions so "npm install" next week matches what was audited today.',
    steps: [
      'Run your package manager to regenerate a lockfile (e.g. "npm install", "uv lock", "go mod tidy").',
      'Commit the resulting package-lock.json / Pipfile.lock / go.sum / Cargo.lock.',
      'Remove it from .gitignore if it was excluded.',
      'Re-assess once the lockfile is on main.',
    ],
  },
  code_owners_exists: {
    label: 'CODEOWNERS file is committed',
    failLabel: 'CODEOWNERS file is missing',
    description:
      'CODEOWNERS auto-requests review from the right owners and is a prereq for owner-required branch protection.',
    steps: [
      'Create .github/CODEOWNERS at the repo root.',
      'Map paths to teams or individuals: e.g. "* @your-org/maintainers".',
      'Commit and push — GitHub auto-requests reviews on the next PR.',
    ],
    docHref:
      'https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners',
    docLabel: 'GitHub: about code owners',
  },
  secret_scanning_enabled: {
    label: 'Secret scanning is enabled',
    failLabel: 'Secret scanning is disabled',
    description:
      'GitHub-side secret scanning catches credentials in pushed commits before they hit a public mirror.',
    steps: [
      'Open Settings → Code security and analysis.',
      'Enable "Secret scanning" (and "Push protection" if available on your plan).',
      'Re-assess once the toggle is on.',
    ],
    docHref:
      'https://docs.github.com/en/code-security/secret-scanning/enabling-secret-scanning-features/enabling-secret-scanning-for-your-repository',
    docLabel: 'GitHub: enabling secret scanning',
  },
  actions_pinned_to_sha: {
    label: 'CI actions are pinned to commit SHAs',
    failLabel: 'CI actions are pinned to mutable refs',
    description:
      'Pinning third-party Actions to commit SHAs (not tags or branches) prevents a rolled tag from silently swapping in malicious code.',
    steps: [
      'Replace each "uses: actions/checkout@v4" in .github/workflows/*.yml with the full commit SHA.',
      'Add a comment with the version label so renovate-style bumpers can still find it.',
      'Repeat for every third-party action in the workflows.',
    ],
    docHref:
      'https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#using-third-party-actions',
    docLabel: 'GitHub: hardening third-party actions',
  },
  trusted_action_sources: {
    label: 'Workflows only call trusted Action sources',
    failLabel: 'Workflows call untrusted Action sources',
    description:
      'Restricting Actions to verified creators and your org reduces the supply-chain blast radius for CI.',
    steps: [
      'Open Settings → Actions → General → Allow specific actions.',
      'Switch to "Allow <org>, and select non-<org> actions" with the verified-creator + reusable-workflows toggles.',
      'Re-assess after saving.',
    ],
  },
  workflow_trigger_scope: {
    label: 'Workflow triggers are scoped (advisory)',
    failLabel: 'Workflow trigger scope is broad (advisory)',
    description:
      'Workflows that combine pull_request_target with checkout of the PR head can run untrusted code with org secrets. Advisory — review every match.',
    steps: [
      'Open the flagged workflow files (linked in the detail).',
      'Remove or replace pull_request_target with pull_request where possible.',
      'If you must keep pull_request_target, never check out the PR head ref in the same job that has secrets.',
    ],
    docHref:
      'https://securitylab.github.com/research/github-actions-preventing-pwn-requests/',
    docLabel: 'Preventing pwn-requests in Actions',
  },
  stale_collaborators: {
    label: 'No stale collaborators',
    failLabel: 'Stale collaborators detected',
    description:
      'Outside collaborators that never touch the repo are credential sprawl — revoke access until they need it.',
    steps: [
      'Open Settings → Collaborators and review the inactive list.',
      'Remove or downgrade access for collaborators who have not contributed in 6+ months.',
      'Re-invite when needed; the audit trail beats permanent access.',
    ],
  },
  broad_team_permissions: {
    label: 'Team permissions are scoped (advisory)',
    failLabel: 'Team permissions are too broad (advisory)',
    description:
      'A team with write access and 20+ members is a wide blast radius. Advisory — judge per team.',
    steps: [
      'Open Settings → Manage access → Team list.',
      'Either split the team into a smaller "writers" subset or downgrade write to triage / read.',
    ],
  },
  default_branch_permissions: {
    label: 'Default branch permissions are scoped',
    failLabel: 'Default branch is writable by too many roles',
    description:
      'Anyone with write access can push to an unprotected default branch — combine with branch protection above.',
    steps: [
      'Open Settings → Branches → Default branch rule.',
      'Add "Restrict who can push to matching branches" and pick a small reviewer set.',
      'Re-assess once saved.',
    ],
  },
}

// Defensive fallback for any check name the backend might emit that we
// don't yet have detailed copy for — keeps the row rendering instead of
// crashing the dashboard.
const FALLBACK_POSTURE_META: (typeof POSTURE_META)[PostureCheckName] = {
  label: 'Posture check',
  failLabel: 'Posture check failed',
  description:
    'See the detail payload for this check’s findings. OpenSec is rolling out per-check guidance; a detailed remediation walkthrough lands in a follow-up release.',
  steps: [
    'Open the "detail" payload to see exactly what the scanner reported.',
    'Re-assess after addressing the underlying configuration.',
  ],
}

const FIXABLE_NAMES: PostureFixableCheck[] = [
  'security_md',
  'dependabot_config',
]

function isFixable(name: PostureCheckName): name is PostureFixableCheck {
  return (FIXABLE_NAMES as readonly string[]).includes(name)
}

const STATUS_ORDER: Record<PostureCheckStatus, number> = {
  fail: 0,
  unknown: 1,
  advisory: 2,
  pass: 3,
}

/**
 * Row-render shape for the dashboard posture card.
 *
 * Derived from the unified ``finding`` table (ADR-0027) — the wire ships
 * ``Finding`` rows with ``type='posture'``; this view collapses them onto
 * the four-state vocabulary the card already speaks. The same shape is
 * also synthesized from ``criteria_snapshot`` for pre-2026-04 assessments
 * that predate posture persistence in the unified table.
 */
interface PostureCheckView {
  id: string
  check_name: PostureCheckName
  status: PostureCheckStatus
  detail: Record<string, unknown> | null
}

function toPostureCheckView(row: Finding): PostureCheckView {
  const raw = (row.raw_payload ?? {}) as {
    check_name?: string
    scanner_status?: PostureCheckStatus
    detail?: Record<string, unknown> | null
  }
  const checkName = (raw.check_name ?? row.title) as PostureCheckName
  let status: PostureCheckStatus
  if (raw.scanner_status) {
    status = raw.scanner_status
  } else if (row.grade_impact === 'advisory') {
    status = 'advisory'
  } else if (row.status === 'passed') {
    status = 'pass'
  } else {
    status = 'fail'
  }
  return {
    id: row.id,
    check_name: checkName,
    status,
    detail: raw.detail ?? null,
  }
}

function PostureCard({
  data,
  onGenerate,
  pending,
  feedback,
  activeWorkspaceIds,
}: {
  data: DashboardPayload
  onGenerate: (
    checkName: PostureFixableCheck,
    params?: PostureFixParams,
  ) => void
  pending: boolean
  feedback: PostureFeedback | null
  activeWorkspaceIds: Partial<Record<PostureFixableCheck, string>>
}) {
  const {
    posture_pass_count,
    posture_total_count,
    criteria_snapshot: criteria,
    posture_checks,
  } = data

  // Project posture findings (unified ``finding`` rows per ADR-0027) into
  // the row-render shape this card consumes. Falls back to a synthesized
  // minimal list for pre-2026-04 assessments whose payloads don't include
  // posture rows.
  const checks: PostureCheckView[] = useMemo(() => {
    if (posture_checks && posture_checks.length > 0) {
      return posture_checks.map(toPostureCheckView)
    }
    const names: PostureCheckName[] = [
      'security_md',
      'dependabot_config',
      'branch_protection',
      'no_force_pushes',
      'no_secrets_in_code',
      'lockfile_present',
      'signed_commits',
    ]
    return names.map((n) => ({
      id: `synth-${n}`,
      check_name: n,
      status:
        n === 'security_md' && criteria.security_md_present
          ? 'pass'
          : n === 'dependabot_config' && criteria.dependabot_present
            ? 'pass'
            : 'unknown',
      detail: null,
    }))
  }, [posture_checks, criteria])

  const sorted = useMemo(
    () =>
      [...checks].sort(
        (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status],
      ),
    [checks],
  )

  const passCount = posture_pass_count ?? 0
  const totalCount = posture_total_count ?? 0
  const pct = totalCount > 0 ? Math.round((passCount / totalCount) * 100) : 0

  return (
    <section className="flex flex-col gap-4 rounded-3xl bg-surface-container-low p-6">
      <header className="flex flex-col gap-2">
        <div
          data-testid="posture-progress-rail"
          aria-hidden
          className="h-1.5 w-40 rounded-full bg-surface-container-high overflow-hidden"
        >
          <div
            className="h-full bg-tertiary transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div>
          <h3 className="font-headline text-lg font-bold text-on-surface">
            Repo posture
          </h3>
          <p className="text-sm text-on-surface-variant">
            {passCount} of {totalCount} checks pass · {pct}% complete · click
            any item for step-by-step guidance
          </p>
        </div>
      </header>

      {feedback && feedback.kind === 'error' && (
        <InlineErrorCallout
          title={`Couldn't open the PR for ${feedback.checkName === 'security_md' ? 'SECURITY.md' : 'Dependabot'}`}
          body={<>{feedback.message}</>}
          action={
            feedback.message.toLowerCase().includes('github integration')
              ? { label: 'Open Settings', href: '/settings' }
              : undefined
          }
        />
      )}
      {feedback && feedback.kind === 'success' && (
        <div
          role="status"
          className="rounded-lg bg-tertiary-container/30 px-4 py-3 flex items-start gap-3"
        >
          <span
            className="material-symbols-outlined text-tertiary flex-shrink-0"
            aria-hidden
          >
            check_circle
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-on-surface">
              Workspace spawned
            </p>
            <p className="text-sm text-on-surface-variant mt-1 leading-relaxed">
              {feedback.message}
            </p>
          </div>
        </div>
      )}

      <ul role="list" className="flex flex-col gap-2">
        {sorted.map((check) => (
          <PostureCheckRow
            key={check.check_name}
            check={check}
            onGenerate={onGenerate}
            pending={pending}
            activeWorkspaceId={
              isFixable(check.check_name)
                ? activeWorkspaceIds[check.check_name]
                : undefined
            }
          />
        ))}
      </ul>
    </section>
  )
}

function PostureCheckRow({
  check,
  onGenerate,
  pending,
  activeWorkspaceId,
}: {
  check: PostureCheckView
  onGenerate: (name: PostureFixableCheck, params?: PostureFixParams) => void
  pending: boolean
  activeWorkspaceId?: string
}) {
  const meta = POSTURE_META[check.check_name] ?? FALLBACK_POSTURE_META
  const [open, setOpen] = useState(check.status === 'fail')
  // security_md is the only auto-fix that benefits from a user-supplied
  // parameter today (the contact email on the generated SECURITY.md).
  // Kept local to the row so it doesn't pollute the card-level state.
  const [contactEmail, setContactEmail] = useState('')

  const tone = statusTone(check.status)
  const label =
    check.status === 'pass' || check.status === 'advisory'
      ? meta.label
      : meta.failLabel

  return (
    <li
      className={`rounded-2xl ${tone.bg} transition-colors`}
      data-testid={`posture-row-${check.check_name}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left hover:bg-surface-container"
      >
        <span
          className={`material-symbols-outlined text-xl ${tone.iconColor}`}
          aria-hidden
        >
          {tone.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-on-surface">{label}</p>
          <p className="text-xs text-on-surface-variant mt-0.5">
            {statusCopy(check.status)}
            {check.status === 'unknown' &&
              ' · likely a missing PAT scope, check Settings.'}
          </p>
        </div>
        <span
          className={`material-symbols-outlined text-on-surface-variant transition-transform ${
            open ? 'rotate-180' : ''
          }`}
          aria-hidden
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 text-sm text-on-surface-variant">
          <p className="mb-3">{meta.description}</p>

          {check.status !== 'pass' && (
            <>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                How to fix
              </p>
              <ol className="ml-4 list-decimal space-y-1.5">
                {meta.steps.map((s, i) => (
                  <li key={i} className="text-sm text-on-surface">
                    {s}
                  </li>
                ))}
              </ol>
            </>
          )}

          {meta.docHref && (
            <a
              href={meta.docHref}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              <span className="material-symbols-outlined text-sm" aria-hidden>
                open_in_new
              </span>
              {meta.docLabel ?? 'Read the docs'}
            </a>
          )}

          {check.status !== 'pass' && isFixable(check.check_name) && (
            <div className="mt-4 flex flex-col gap-3 border-t border-outline-variant/30 pt-3">
              {check.check_name === 'security_md' && !activeWorkspaceId && (
                <label
                  className="flex flex-col gap-1 text-xs font-medium text-on-surface-variant"
                  htmlFor={`contact-email-${check.check_name}`}
                >
                  Contact email for vulnerability reports
                  <span className="font-normal text-on-surface-variant/80">
                    Optional. If you leave this blank the generated
                    SECURITY.md ships with a clearly-labelled placeholder
                    you can edit before merging.
                  </span>
                  <input
                    id={`contact-email-${check.check_name}`}
                    type="email"
                    inputMode="email"
                    placeholder="security@your-project.org"
                    value={contactEmail}
                    onChange={(e) => setContactEmail(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    className="mt-1 w-full rounded-lg bg-surface-container-lowest px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  />
                </label>
              )}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (!isFixable(check.check_name)) return
                    const params: PostureFixParams = {}
                    if (check.check_name === 'security_md' && contactEmail.trim()) {
                      params.contact_email = contactEmail.trim()
                    }
                    onGenerate(
                      check.check_name,
                      Object.keys(params).length > 0 ? params : undefined,
                    )
                  }}
                  disabled={pending || Boolean(activeWorkspaceId)}
                  className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-sm" aria-hidden>
                    play_arrow
                  </span>
                  Let OpenSec open a PR
                </button>
                <span className="text-xs text-on-surface-variant">
                  Opens a draft PR you review before merging.
                </span>
              </div>
              {activeWorkspaceId && (
                <PostureFixStatusStrip workspaceId={activeWorkspaceId} />
              )}
            </div>
          )}

          {check.detail && Object.keys(check.detail).length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                Check detail (JSON)
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-surface-container p-3 text-xs text-on-surface">
                {JSON.stringify(check.detail, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </li>
  )
}

function PostureFixStatusStrip({ workspaceId }: { workspaceId: string }) {
  const { data, isLoading } = usePostureFixStatus(workspaceId)
  const status = data?.status ?? (isLoading ? 'queued' : 'queued')

  let icon = 'hourglass_top'
  let tone = 'text-on-surface-variant'
  let label = 'Starting the generator agent…'

  if (status === 'queued') {
    label = 'Agent queued — spinning up OpenCode…'
  } else if (status === 'running') {
    label = 'Agent running — cloning, writing, committing, pushing…'
  } else if (status === 'pr_created') {
    icon = 'check_circle'
    tone = 'text-tertiary'
    label = 'Draft PR opened and ready for your review.'
  } else if (status === 'already_present') {
    icon = 'info'
    tone = 'text-on-surface-variant'
    label = 'No change needed — the file was already present and complete.'
  } else if (status === 'failed') {
    icon = 'error'
    tone = 'text-error'
    label = data?.error || 'The agent failed before opening a PR.'
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-2 rounded-lg bg-surface-container-lowest px-3 py-2"
    >
      <span
        className={`material-symbols-outlined text-base ${tone}`}
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-on-surface">{label}</p>
        {data?.pr_url && (
          <a
            href={data.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
          >
            <span className="material-symbols-outlined text-xs" aria-hidden>
              open_in_new
            </span>
            Review {data.pr_url.replace('https://github.com/', '')}
          </a>
        )}
        <p className="mt-0.5 text-[10px] text-on-surface-variant/80">
          workspace {workspaceId}
        </p>
      </div>
    </div>
  )
}

function statusTone(status: PostureCheckStatus): {
  icon: string
  iconColor: string
  bg: string
} {
  switch (status) {
    case 'pass':
      return {
        icon: 'check_circle',
        iconColor: 'text-tertiary',
        bg: 'bg-surface-container',
      }
    case 'advisory':
      return {
        icon: 'info',
        iconColor: 'text-on-surface-variant',
        bg: 'bg-surface-container',
      }
    case 'unknown':
      return {
        icon: 'help',
        iconColor: 'text-on-surface-variant',
        bg: 'bg-surface-container',
      }
    case 'fail':
    default:
      return {
        icon: 'error',
        iconColor: 'text-primary',
        bg: 'bg-primary-container/25',
      }
  }
}

function statusCopy(status: PostureCheckStatus): string {
  switch (status) {
    case 'pass':
      return 'Passing'
    case 'advisory':
      return 'Recommended'
    case 'unknown':
      return 'Unable to verify'
    case 'fail':
    default:
      return 'Needs attention'
  }
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
