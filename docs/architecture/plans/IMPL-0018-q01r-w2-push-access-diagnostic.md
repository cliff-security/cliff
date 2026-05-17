# IMPL-0018: Q01R Wave 2 — push-access diagnostic on Settings page

**Scope:** Wave 2 (Q01R-W2) bug fix — surface push-access problems before users click Approve
**Bug:** B35c (P1)
**Owner:** App Builder (V2) — `backend/opensec/api/routes/`, `frontend/src/pages/SettingsPage.tsx`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

After IMPL-0017 lands, the preflight will correctly block the executor before wasting a run. But users won't know there's a problem until they try to Approve and get a 412. A proactive diagnostic on the Settings → Integrations → GitHub card surfaces the same information at the point where users naturally check setup status, days before they try to fix a finding.

**Add `GET /api/integrations/github/diagnose`** that calls the same enhanced `check_repo_push_access` from IMPL-0017 against the currently-configured repo, returns a structured result, and is rendered as a green/red badge on the Settings page's GitHub integration card with the same "How to fix" link the executor's error card uses.

This is small. The endpoint is a thin wrapper around the existing helper. The Settings UI gets a one-line badge.

## Root cause (grounded)

Not a bug per se — a missing observability surface. Today the user discovers push problems only when an executor run fails. After IMPL-0017 the discovery point moves to "click Approve" — still reactive. The diagnostic surfaces the same information proactively.

## Files touched

Backend (V2):
- `backend/opensec/api/routes/ai_integrations.py` (or wherever GitHub routes live) — add `GET /api/integrations/github/diagnose`:
  - Resolve the configured repo URL (same logic as `_resolve_repo_env_vars`)
  - Call `check_repo_push_access` with the stored token
  - Return `{can_push: bool, reason: str, repo_url: str, checked_at: iso8601}`
- `backend/tests/test_routes_github_diagnose.py` — new file, 3 tests:
  - `test_returns_can_push_true_when_perms_ok`
  - `test_returns_can_push_false_with_org_admin_message_when_install_perms_insufficient`
  - `test_returns_404_when_github_not_configured`

Frontend (V2):
- `frontend/src/pages/SettingsPage.tsx` (or wherever the GitHub integration card lives — grep for "GitHub" in `frontend/src/components/settings/`) — add a `<PushAccessBadge>` sub-component:
  - On Settings page mount, fetch `/api/integrations/github/diagnose`
  - Render: green "Push verified" if `can_push=true`; red "Push blocked: {reason}" if false; with a "How to fix" link to the same anchor used in IMPL-0017
- `frontend/src/api/githubIntegration.ts` — `useGitHubPushDiagnose` hook
- `frontend/src/components/settings/__tests__/PushAccessBadge.test.tsx` — test rendering of both states

Docs:
- `docs/guides/setup-github-app.md` — add a "How to verify push access" section that points at the Settings page badge

## Test plan (TDD-first)

Backend:
```python
# test_routes_github_diagnose.py
def test_returns_can_push_false_with_org_admin_message(...):
    # mock check_repo_push_access to return can_push=False with org-admin reason
    resp = client.get("/api/integrations/github/diagnose")
    assert resp.status_code == 200
    assert resp.json()["can_push"] is False
    assert "admin" in resp.json()["reason"].lower()
```

Frontend:
```tsx
// PushAccessBadge.test.tsx
it("renders green badge when can_push is true", async () => {
  server.use(rest.get("/api/integrations/github/diagnose", (_, res, ctx) =>
    res(ctx.json({ can_push: true, reason: "", repo_url: "...", checked_at: "..." }))))
  render(<PushAccessBadge />)
  await waitFor(() => expect(screen.getByText(/push verified/i)).toBeInTheDocument())
})
```

E2E (Wave 3 QA):
- Open Settings on the wave-2-broken setup (install missing newer perms): see red badge with "org admin needs to approve" message + How-to-fix link
- After org admin approves: refresh Settings → green badge

## Risks

- **Diagnose endpoint fetches GitHub on every Settings page load.** Mitigation: cache the result for 5 min in the API layer; expose a "refresh" button on the badge that bypasses cache.
- **Could leak token or repo URL in error messages.** Mitigation: `check_repo_push_access` already returns sanitized reasons; just verify nothing new gets added.

## ADR

Amends ADR-0037 — see the amendment block to add "Runtime verification of push access is required because user OAuth tokens carry user×App×Installation intersection that isn't visible from the App's declared permissions alone."

## Rollout

Single PR, 3 commits:
1. `feat(q01r-w2-diagnose): GET /api/integrations/github/diagnose endpoint (B35c)`
2. `feat(q01r-w2-diagnose): Settings push-access badge`
3. `docs(q01r-w2-diagnose): explain the diagnose flow`

Target branch: `main`.
