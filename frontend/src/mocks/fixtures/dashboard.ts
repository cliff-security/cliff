/**
 * Dashboard API fixtures for MSW handlers and tests.
 *
 * Three seeded states per EXEC-0002 Session E contract:
 *   - assessment-running        — scan in-flight, no grade yet
 *   - grade-C-with-issues       — 3 of 5 criteria met, vulns + failing posture
 *   - grade-A-completion-holding — 5 of 5 criteria met, completion active
 */

import type { components } from '@/api/types'

export type DashboardPayload = components['schemas']['DashboardPayload']
export type Assessment = components['schemas']['Assessment']
export type AssessmentStatusResponse =
  components['schemas']['AssessmentStatusResponse']
export type Finding = components['schemas']['Finding']
export type PostureFixResponse = components['schemas']['PostureFixResponse']
export type CriteriaSnapshot = components['schemas']['CriteriaSnapshot']

// ---------------------------------------------------------------------------
// Common timestamps
// ---------------------------------------------------------------------------

const NOW = '2026-04-16T09:00:00Z'
const EARLIER = '2026-04-16T08:30:00Z'

// ---------------------------------------------------------------------------
// Assessment objects (match frozen schema — status: pending|running|complete|failed)
// ---------------------------------------------------------------------------

const runningAssessment: Assessment = {
  id: 'asmt_running_001',
  repo_url: 'https://github.com/acme/fast-markdown',
  status: 'running',
  grade: null,
  started_at: EARLIER,
  completed_at: null,
  criteria_snapshot: null,
}

// The 7 posture checks here are the "other" governance checks (branch
// protection, signed commits, code scanning, etc.) — disjoint from
// security_md_present + dependabot_present, which are separate completion
// criteria. This disjointness is what makes "3 of 5 criteria met" + "7 of 7
// posture checks passing" + "2 failing items to fix" internally consistent.
const _legacyEmptyCriteria = {
  security_md_present: false,
  dependabot_present: false,
  no_critical_vulns: false,
  posture_checks_passing: 0,
  posture_checks_total: 0,
  no_high_vulns: false,
  branch_protection_enabled: false,
  no_secrets_detected: false,
  actions_pinned_to_sha: false,
  no_stale_collaborators: false,
  code_owners_exists: false,
  secret_scanning_enabled: false,
}

const completedAssessmentC: Assessment = {
  id: 'asmt_c_001',
  repo_url: 'https://github.com/acme/fast-markdown',
  status: 'complete',
  grade: 'C',
  started_at: EARLIER,
  completed_at: NOW,
  // PR-B (PRD-0003 v0.2): pre-mark the interstitial as seen so completed
  // fixtures fall through to the report card instead of the Surface 3 gate.
  summary_seen_at: NOW,
  criteria_snapshot: {
    ..._legacyEmptyCriteria,
    no_critical_vulns: true,
    posture_checks_passing: 7,
    posture_checks_total: 7,
  },
}

const completedAssessmentA: Assessment = {
  id: 'asmt_a_001',
  repo_url: 'https://github.com/acme/fast-markdown',
  status: 'complete',
  grade: 'A',
  started_at: EARLIER,
  completed_at: NOW,
  summary_seen_at: NOW,
  criteria_snapshot: {
    ..._legacyEmptyCriteria,
    security_md_present: true,
    dependabot_present: true,
    no_critical_vulns: true,
    no_high_vulns: true,
    posture_checks_passing: 15,
    posture_checks_total: 15,
    branch_protection_enabled: true,
    no_secrets_detected: true,
    actions_pinned_to_sha: true,
    no_stale_collaborators: true,
    code_owners_exists: true,
    secret_scanning_enabled: true,
  },
}

// ---------------------------------------------------------------------------
// Payloads
// ---------------------------------------------------------------------------

// v0.2 (ADR-0032): `criteria` is the labeled list; `criteria_snapshot` keeps
// the legacy boolean record for backward compatibility.
const _emptySnapshot = {
  security_md_present: false,
  dependabot_present: false,
  no_critical_vulns: false,
  posture_checks_passing: 0,
  posture_checks_total: 0,
  no_high_vulns: false,
  branch_protection_enabled: false,
  no_secrets_detected: false,
  actions_pinned_to_sha: false,
  no_stale_collaborators: false,
  code_owners_exists: false,
  secret_scanning_enabled: false,
}

const _criteriaForSnapshot = (snap: typeof _emptySnapshot) => [
  { key: 'security_md_present', label: 'SECURITY.md present', met: snap.security_md_present },
  { key: 'dependabot_configured', label: 'Dependabot configured', met: snap.dependabot_present },
  { key: 'no_critical_vulns', label: 'No critical vulns', met: snap.no_critical_vulns },
  { key: 'no_high_vulns', label: 'No high vulns', met: snap.no_high_vulns },
  {
    key: 'branch_protection_enabled',
    label: 'Branch protection enabled',
    met: snap.branch_protection_enabled,
  },
  { key: 'no_secrets_detected', label: 'No committed secrets', met: snap.no_secrets_detected },
  {
    key: 'actions_pinned_to_sha',
    label: 'CI actions pinned to SHA',
    met: snap.actions_pinned_to_sha,
  },
  {
    key: 'no_stale_collaborators',
    label: 'No stale collaborators',
    met: snap.no_stale_collaborators,
  },
  { key: 'code_owners_exists', label: 'Code owners file exists', met: snap.code_owners_exists },
  {
    key: 'secret_scanning_enabled',
    label: 'Secret scanning enabled',
    met: snap.secret_scanning_enabled,
  },
]

export const assessmentRunningPayload: DashboardPayload = {
  assessment: runningAssessment,
  completion_id: null,
  criteria: _criteriaForSnapshot(_emptySnapshot),
  criteria_snapshot: _emptySnapshot,
  findings_count_by_priority: {},
  grade: null,
  posture_checks: [],
  posture: null,
  posture_pass_count: 0,
  posture_total_count: 0,
  tools: [],
  vulnerabilities: null,
  grade_label: 'First scan',
  grade_caption: 'Run your first assessment to earn a grade.',
}

const _snapshotC = {
  ..._emptySnapshot,
  // PRD-0003 v0.2: grade C requires 6–7 of the 10 grade-counting criteria
  // met. Set six explicit True values so the dashboard's criteria meter
  // and the GradeRing's "X of 10" display agree with the headline grade.
  // (Pre-PR, this snapshot only set ``no_critical_vulns`` and relied on
  // the legacy 5-bucket counter to inflate the displayed count to 3 — see
  // the dogfooding bug log entry on the dashboard count mismatch.)
  no_critical_vulns: true,
  no_high_vulns: true,
  security_md_present: true,
  dependabot_present: true,
  no_secrets_detected: true,
  code_owners_exists: true,
  posture_checks_passing: 7,
  posture_checks_total: 7,
}

export const gradeCWithIssuesPayload: DashboardPayload = {
  assessment: completedAssessmentC,
  completion_id: null,
  criteria: _criteriaForSnapshot(_snapshotC),
  criteria_snapshot: _snapshotC,
  findings_count_by_priority: {
    critical: 1,
    high: 2,
    medium: 3,
    low: 1,
  },
  grade: 'C',
  posture_checks: [],
  posture: null,
  posture_pass_count: 7,
  posture_total_count: 7,
  tools: [],
  vulnerabilities: null,
  grade_label: 'Stable',
  grade_caption: 'Steady at C. Two more closures away from B.',
}

const _snapshotA = {
  ..._emptySnapshot,
  security_md_present: true,
  dependabot_present: true,
  no_critical_vulns: true,
  no_high_vulns: true,
  posture_checks_passing: 15,
  posture_checks_total: 15,
  branch_protection_enabled: true,
  no_secrets_detected: true,
  actions_pinned_to_sha: true,
  no_stale_collaborators: true,
  code_owners_exists: true,
  secret_scanning_enabled: true,
}

export const gradeACompletionHoldingPayload: DashboardPayload = {
  assessment: completedAssessmentA,
  completion_id: 'cmp_001',
  criteria: _criteriaForSnapshot(_snapshotA),
  criteria_snapshot: _snapshotA,
  findings_count_by_priority: {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
  },
  grade: 'A',
  posture_checks: [],
  posture: null,
  posture_pass_count: 7,
  posture_total_count: 7,
  tools: [],
  vulnerabilities: null,
  grade_label: 'Stable',
  grade_caption: "You're at A — hold the line.",
}

// ---------------------------------------------------------------------------
// PRD-0006 Phase 2 — grade-B-with-history fixture
//
// Carries the full Phase 2 add-on payload (open_issues + time_to_close +
// needs_you + grade_history + severity_history) so the new IssueGradeHero,
// IssueNeedsYouLine, IssueMetricCard, and IssueGradeHistoryChart components
// have realistic data to render in the page tests.
// ---------------------------------------------------------------------------

const completedAssessmentB: Assessment = {
  id: 'asmt_b_001',
  repo_url: 'https://github.com/acme/fast-markdown',
  status: 'complete',
  grade: 'B',
  started_at: EARLIER,
  completed_at: NOW,
  summary_seen_at: NOW,
  criteria_snapshot: {
    ..._legacyEmptyCriteria,
    no_critical_vulns: true,
    no_high_vulns: true,
    security_md_present: true,
    dependabot_present: true,
    no_secrets_detected: true,
    code_owners_exists: true,
    branch_protection_enabled: true,
    posture_checks_passing: 12,
    posture_checks_total: 15,
  },
}

const _snapshotB = {
  ..._emptySnapshot,
  no_critical_vulns: true,
  no_high_vulns: true,
  security_md_present: true,
  dependabot_present: true,
  no_secrets_detected: true,
  code_owners_exists: true,
  branch_protection_enabled: true,
  posture_checks_passing: 12,
  posture_checks_total: 15,
}

// 30-day open-issues series — fictional but plausibly trending downward.
const _openIssuesHistory = [
  72, 70, 70, 68, 68, 67, 65, 64, 62, 60,
  58, 57, 55, 54, 52, 50, 48, 47, 45, 44,
  42, 40, 38, 37, 36, 34, 32, 30, 28, 26,
]

// 30-day time-to-close p50 (seconds) series with a few quiet days.
const _ttcHistory: Array<number | null> = [
  86400, 82800, 79200, null, 75600, 72000, null, 68400, 64800, 61200,
  null, 57600, 54000, 50400, null, 46800, 43200, 39600, 36000, null,
  32400, 28800, 25200, null, 21600, 18000, null, 15300, 12600, 11520,
]

const _gradeHistoryB: Array<{
  date: string
  grade: 'A' | 'B' | 'C' | 'D' | 'F' | null
}> = (() => {
  const out: Array<{
    date: string
    grade: 'A' | 'B' | 'C' | 'D' | 'F' | null
  }> = []
  for (let i = 89; i >= 0; i -= 1) {
    let grade: 'A' | 'B' | 'C' | 'D' | 'F' | null = null
    if (i === 0) grade = 'B' // today
    else if (i === 17) grade = 'B' // promotion 17 days ago
    else if (i === 18) grade = 'C' // previous letter
    else if (i === 50) grade = 'C'
    else if (i === 89) grade = 'D'
    out.push({
      date: `2026-04-${String(20 - (i % 30)).padStart(2, '0')}`,
      grade,
    })
  }
  return out.reverse()
})()

const _severityHistoryB = {
  critical: Array.from({ length: 60 }, (_, i) => (i < 50 ? 1 : 0)),
  high: Array.from({ length: 60 }, (_, i) => Math.max(0, 9 - Math.floor(i / 8))),
  medium: Array.from({ length: 60 }, (_, i) => 26 - Math.floor(i / 4)),
  low: Array.from({ length: 60 }, (_, i) => 24 - Math.floor(i / 6)),
}

export const gradeBWithHistoryPayload: DashboardPayload = {
  assessment: completedAssessmentB,
  completion_id: null,
  criteria: _criteriaForSnapshot(_snapshotB),
  criteria_snapshot: _snapshotB,
  findings_count_by_priority: {
    critical: 1,
    high: 9,
    medium: 26,
    low: 24,
  },
  grade: 'B',
  posture_checks: [],
  posture: null,
  posture_pass_count: 12,
  posture_total_count: 15,
  tools: [],
  vulnerabilities: {
    total: 60,
    by_severity: { critical: 1, high: 9, medium: 26, low: 24 },
    by_source: { dependency: 50, code: 8, secret: 2 },
    tool_credits: ['trivy', 'semgrep'],
  },
  open_issues: {
    current: 26,
    history: _openIssuesHistory,
    delta_pct_30d: -64,
  },
  time_to_close: {
    current_seconds: 11520,
    history: _ttcHistory,
    delta_pct_30d: -86,
  },
  needs_you: {
    plans_waiting: 3,
    prs_ready: 2,
    critical_todo: 1,
  },
  grade_history: _gradeHistoryB,
  severity_history: _severityHistoryB,
  grade_label: 'Stable',
  grade_caption: 'Promoted from C 17 days ago. Two more closures away from A.',
  open_by_severity: [
    { kind: 'critical', count: 1, weekly_delta: -1 },
    { kind: 'high', count: 9, weekly_delta: -3 },
    { kind: 'medium', count: 26, weekly_delta: -1 },
    { kind: 'low', count: 24, weekly_delta: 0 },
  ],
  level_up: {
    current: 'B',
    next: 'A',
    summary: 'Three things between you and an A. Two are one-click.',
    gates: [
      {
        id: 'criticals_open',
        label: 'Close the open Critical',
        detail: 'RCE in lodash chain · plan ready for your review',
        current: 1,
        target: 0,
        unit: 'critical',
        status: 'ready_to_review',
        action_label: 'Review plan',
        action_href: '/issues?open=fnd_001',
        auto_fixable_check_names: [],
      },
      {
        id: 'secrets_open',
        label: 'Resolve the committed secret',
        detail: 'Stripe live key · PR #1842 ready',
        current: 1,
        target: 0,
        unit: 'secret',
        status: 'pr_ready',
        action_label: 'Open PR',
        action_href: '/issues?open=fnd_secret_001',
        auto_fixable_check_names: [],
      },
      {
        id: 'posture_remaining',
        label: 'Pass remaining posture checks',
        detail: 'security_md, code_owners_exists',
        current: 12,
        target: 15,
        unit: 'posture checks',
        status: 'auto_fixable',
        action_label: 'Auto-fix 2 of 3',
        action_href: '/issues?type=posture',
        auto_fixable_check_names: ['security_md', 'code_owners_exists'],
      },
    ],
  },
  last_assessment: {
    repo_url: 'https://github.com/acme/fast-markdown',
    finished_at: NOW,
    duration_ms: 257_000,
    commit_sha: 'a3f81c2',
    branch: 'main',
    scanned_files: 4128,
    scanned_deps: 312,
    scanners: [
      {
        id: 'trivy',
        label: 'Trivy 0.52.2',
        icon: 'bug_report',
        state: 'done',
        version: '0.52.2',
        duration_ms: 38_400,
        scope: '312 deps · npm + pip · git history',
        ran: 'Dependency + secret scan',
        result: { kind: 'findings_count', value: 7, text: '7 findings' },
      },
      {
        id: 'semgrep',
        label: 'Semgrep 1.70.0',
        icon: 'code',
        state: 'done',
        version: '1.70.0',
        duration_ms: 71_200,
        scope: '4128 files · p/security-audit',
        ran: 'Static analysis (p/security-audit)',
        result: { kind: 'findings_count', value: 3, text: '3 findings' },
      },
      {
        id: 'posture',
        label: '15 posture checks',
        icon: 'rule',
        state: 'done',
        version: '1.0.0',
        duration_ms: 9_600,
        scope: '15 repo + cloud configuration checks',
        ran: '15 repo + cloud configuration checks',
        result: { kind: 'pass_count', value: 12, text: '12 pass' },
      },
    ],
  },
}

// ---------------------------------------------------------------------------
// Findings (plain-language, for FindingRow + FindingDetailPage)
// ---------------------------------------------------------------------------

export const sampleFindings: Finding[] = [
  {
    id: 'fnd_001',
    source_type: 'osv',
    source_id: 'CVE-2024-4067',
    title: 'A pattern-matching library your project uses has a known flaw',
    description:
      'The braces npm package can be tricked into infinite loops when handed malicious input.',
    plain_description:
      'The braces npm package can be tricked into infinite loops when handed malicious input. The fix is a one-line bump: braces 3.0.2 → 3.0.3.',
    raw_severity: 'critical',
    normalized_priority: 'critical',
    asset_id: 'pkg_braces',
    asset_label: 'braces@3.0.2',
    status: 'new',
    likely_owner: null,
    why_this_matters: null,
    type: 'dependency',
    grade_impact: 'counts',
    raw_payload: {
      cve: 'CVE-2024-4067',
      cvss_score: 7.5,
      attack_vector: 'regex denial-of-service',
    },
    created_at: EARLIER,
    updated_at: NOW,
  },
  {
    id: 'fnd_002',
    source_type: 'osv',
    source_id: 'CVE-2023-45857',
    title: 'Your HTTP client leaks session tokens through a secondary request',
    description:
      'axios versions before 1.6.0 forward authorization headers on cross-origin redirects.',
    plain_description:
      'axios versions before 1.6.0 forward authorization headers on cross-origin redirects. Bump to 1.6.0 or later.',
    raw_severity: 'high',
    normalized_priority: 'high',
    asset_id: 'pkg_axios',
    asset_label: 'axios@1.5.1',
    status: 'new',
    likely_owner: null,
    why_this_matters: null,
    type: 'dependency',
    grade_impact: 'counts',
    raw_payload: {
      cve: 'CVE-2023-45857',
      cvss_score: 6.5,
      attack_vector: 'credential leak via redirect',
    },
    created_at: EARLIER,
    updated_at: NOW,
  },
]

// ---------------------------------------------------------------------------
// Assessment status progression (for poll/SSE — Session B upgrades to SSE later)
// ---------------------------------------------------------------------------

const _emptyTools: AssessmentStatusResponse['tools'] = []

// Step taxonomy mirrors backend/opensec/api/routes/assessment.py::_V2_STEPS_ORDER.
// Keep these in lockstep with the backend; the route is the source of truth
// for the live UI but the MSW fixture has to ship the same shape.
const V2_STEPS: Array<{ key: string; label: string; hint: string | null }> = [
  { key: 'detect', label: 'Detecting project type', hint: null },
  { key: 'trivy_vuln', label: 'Scanning dependencies with Trivy', hint: null },
  { key: 'trivy_secret', label: 'Scanning for secrets with Trivy', hint: null },
  { key: 'semgrep', label: 'Scanning code with Semgrep', hint: null },
  { key: 'posture', label: 'Checking repo posture', hint: '15 checks' },
  {
    key: 'descriptions',
    label: 'Generating plain-language descriptions',
    hint: null,
  },
]

function buildSteps(
  liveStep: string | null,
  status: AssessmentStatusResponse['status'],
): AssessmentStatusResponse['steps'] {
  const cursor = liveStep
  let seenRunning = false
  return V2_STEPS.map(({ key, label, hint }) => {
    let state: 'pending' | 'running' | 'done' | 'skipped'
    if (status === 'complete') {
      state = 'done'
    } else if (status === 'pending') {
      state = 'pending'
    } else if (status === 'failed') {
      state = 'skipped'
    } else if (key === cursor) {
      state = 'running'
      seenRunning = true
    } else if (!seenRunning) {
      state = 'done'
    } else {
      state = 'pending'
    }
    return {
      key,
      label,
      state,
      hint: state === 'pending' ? hint : null,
    } as AssessmentStatusResponse['steps'][number]
  })
}

export const assessmentStatusSteps: AssessmentStatusResponse[] = [
  {
    assessment_id: runningAssessment.id,
    status: 'running',
    progress_pct: 10,
    step: 'detect',
    steps: buildSteps('detect', 'running'),
    tools: _emptyTools,
  },
  {
    assessment_id: runningAssessment.id,
    status: 'running',
    progress_pct: 25,
    step: 'trivy_vuln',
    steps: buildSteps('trivy_vuln', 'running'),
    tools: _emptyTools,
  },
  {
    assessment_id: runningAssessment.id,
    status: 'running',
    progress_pct: 60,
    step: 'semgrep',
    steps: buildSteps('semgrep', 'running'),
    tools: _emptyTools,
  },
  {
    assessment_id: runningAssessment.id,
    status: 'running',
    progress_pct: 80,
    step: 'posture',
    steps: buildSteps('posture', 'running'),
    tools: _emptyTools,
  },
  {
    assessment_id: runningAssessment.id,
    status: 'running',
    progress_pct: 95,
    step: 'descriptions',
    steps: buildSteps('descriptions', 'running'),
    tools: _emptyTools,
  },
  {
    assessment_id: runningAssessment.id,
    status: 'complete',
    progress_pct: 100,
    step: null,
    steps: buildSteps(null, 'complete'),
    tools: _emptyTools,
  },
]

// ---------------------------------------------------------------------------
// Named selector used by tests + handlers to choose active fixture
// ---------------------------------------------------------------------------

export type DashboardFixtureName =
  | 'assessment-running'
  | 'grade-C-with-issues'
  | 'grade-A-completion-holding'
  | 'grade-B-with-history'

export function getDashboardFixture(
  name: DashboardFixtureName,
): DashboardPayload {
  switch (name) {
    case 'assessment-running':
      return assessmentRunningPayload
    case 'grade-C-with-issues':
      return gradeCWithIssuesPayload
    case 'grade-A-completion-holding':
      return gradeACompletionHoldingPayload
    case 'grade-B-with-history':
      return gradeBWithHistoryPayload
  }
}
