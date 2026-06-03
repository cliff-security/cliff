/**
 * PostureCard — repo-posture rail + expandable per-check rows.
 *
 * Extracted verbatim from DashboardPage.tsx (PRD-0006 Phase 2 / IMPL-0007 PR-B
 * F11a refactor — no behavior change). The Dashboard rebuild in F11b keeps
 * this card on the new report-card body while the rest of the surface is
 * replaced; isolating it here makes that diff reviewable.
 */
import { useMemo, useState } from 'react'
import type {
  DashboardPayload,
  Finding,
  PostureCheckName,
  PostureCheckStatus,
  PostureFixableCheck,
  PostureFixParams,
} from '@/api/dashboard'
import { usePostureFixStatus } from '@/api/dashboard'
import InlineErrorCallout from '@/components/onboarding/InlineErrorCallout'

export interface PostureFeedback {
  kind: 'success' | 'error'
  checkName: PostureFixableCheck
  message: string
}

// Per-check metadata: label, what-it-checks blurb, and ordered fix steps.
// The two "auto-fix" checks (security_md, dependabot_config) show a
// primary "Generate and open PR" CTA *in addition* to the manual steps so
// maintainers can either let Cliff do it or do it themselves.
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
      'Commit and push to main — Cliff re-detects on the next assessment.',
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
      'Declare a package-ecosystem entry for each lockfile Cliff detected.',
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
      'Save the rule, then re-assess in Cliff.',
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
      'Cliff scans for high-specificity tokens: AWS AKIA keys, GitHub ghp_/ghs_, Stripe sk_live_, Google AIza, and PEM blocks.',
    steps: [
      'Open the "detail" payload for this check to see which files matched.',
      'Remove the secret from the file and rotate the credential immediately — assume it is leaked.',
      'Add the pattern to .gitignore if it was a config file that should never be tracked.',
      'For historical removal, consider "git filter-repo" or the BFG Repo-Cleaner, then force-push (careful).',
      'Add an entry to .cliff/secrets-ignore only after you are sure the match is a false positive.',
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
    'See the detail payload for this check’s findings. Cliff is rolling out per-check guidance; a detailed remediation walkthrough lands in a follow-up release.',
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

export default function PostureCard({
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
                  Let Cliff open a PR
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
    label = 'Agent queued — starting…'
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
