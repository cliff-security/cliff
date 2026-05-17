/**
 * <PushAccessBadge> — Settings page push-access pill (IMPL-0018 / B35c).
 *
 * Calls ``GET /api/integrations/github/diagnose`` on mount and renders:
 *
 *   - green "Push verified" pill when can_push=true
 *   - red "Push blocked: {reason}" pill + "How to fix" link when can_push=false
 *   - nothing on 404 (no GitHub integration configured — the existing
 *     "Connect GitHub" surface owns that state)
 *
 * The badge surfaces the same information the executor's 412 preflight
 * surfaces, but on Settings page mount so the user catches a
 * misconfigured GitHub App at the natural "check setup" spot — not
 * after waiting 4 minutes for an executor run to fail at git-push time.
 *
 * The "How to fix" link deep-links to the same docs anchor the
 * IssueSidePanel error card uses (kept in sync via a shared constant).
 */

import { useGitHubPushDiagnose } from '@/api/githubApp'

/**
 * Docs anchor the "How to fix" link deep-links to. Kept identical to
 * the constant in ``IssueSidePanel.tsx`` and the backend's
 * ``GITHUB_APP_PERMS_DOC_URL`` (in ``agent_execution.py``) so all three
 * surfaces point at the same set of remediation steps. If you change it,
 * change it in all three places.
 */
const GITHUB_APP_PERMS_DOC_URL =
  '/docs/guides/setup-github-app.md#required-permissions'

export function PushAccessBadge() {
  const { data, isLoading } = useGitHubPushDiagnose()

  // Loading or 404 → render nothing. We deliberately don't show a
  // skeleton: the badge is a passive signal, not a blocking call-to-
  // action. A flash of "checking…" then a green pill would draw the
  // eye unnecessarily on every Settings mount.
  if (isLoading) return null
  if (!data) return null

  if (data.can_push) {
    return (
      <div
        data-testid="push-access-badge"
        role="status"
        aria-label="GitHub push access verified"
        className="inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-semibold"
        style={{
          background: 'var(--cd-green-soft)',
          color: 'var(--cd-green)',
          border: '1px solid var(--cd-green-line)',
        }}
      >
        <span
          aria-hidden
          className="material-symbols-outlined"
          style={{ fontSize: 14 }}
        >
          verified
        </span>
        Push verified
      </div>
    )
  }

  // can_push=false — render the red pill with the backend's reason and
  // the deep-link to the setup guide. The reason string comes from
  // ``check_repo_push_access`` and is already wrapped in Cliff voice
  // ("An org admin needs to approve…") — do NOT re-format it here, or
  // the badge and the IssueSidePanel 412 card will drift.
  return (
    <div
      data-testid="push-access-badge"
      role="status"
      aria-label="GitHub push access blocked"
      className="rounded-md px-3 py-2 text-xs"
      style={{
        background: 'var(--cd-red-soft)',
        color: 'var(--cd-red)',
        border: '1px solid rgba(233, 122, 142, 0.30)',
      }}
    >
      <div
        className="inline-flex items-center gap-2 font-semibold"
        style={{ marginBottom: 4 }}
      >
        <span
          aria-hidden
          className="material-symbols-outlined"
          style={{ fontSize: 14 }}
        >
          block
        </span>
        Push blocked
      </div>
      <div style={{ fontWeight: 400, lineHeight: 1.4 }}>{data.reason}</div>
      <a
        href={GITHUB_APP_PERMS_DOC_URL}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 mt-2 font-semibold underline"
      >
        How to fix
        <span
          aria-hidden
          className="material-symbols-outlined"
          style={{ fontSize: 12 }}
        >
          open_in_new
        </span>
      </a>
    </div>
  )
}
