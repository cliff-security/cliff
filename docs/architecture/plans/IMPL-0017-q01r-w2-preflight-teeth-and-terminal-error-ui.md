# IMPL-0017: Q01R Wave 2 — preflight with real teeth + side-panel terminal-error state

**Scope:** Wave 2 (Q01R-W2) bug fix — executor preflight + UI reactivity
**Bug:** B35a (P1) + B35b (P1)
**Owner:** App Builder (V2) — `backend/opensec/integrations/github_app/`, `backend/opensec/api/routes/agent_execution.py`, `frontend/src/components/issues/IssueSidePanel.tsx`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

Two related-but-distinct bugs ship together because they're the same user story: "the executor said it was working, but my fix never reached GitHub, and the UI kept saying 'pushing'."

- **B35a (P1)** — Preflight `check_repo_push_access` IS wired (verified at `agent_execution.py:194`), but consults the wrong source of truth. The current check `GET /repos/{owner}/{repo}` returns `permissions.push=true` based on the *user's* repo permissions. The actual `git push` then fails because the App's user-OAuth token has `user × App × Installation` intersection that excludes write at the git-protocol level. Preflight passes, push fails, 4 minutes wasted.
- **B35b (P1)** — When the executor finishes with `status=completed` AND `structured_output.error_details != null`, the side panel's TOP widget + status pill stay on "Pushing branch / Thinking…" indefinitely. The ActivityRunErrorCard (PR #168) renders the error correctly inside the activity log, but the panel header sends a contradictory "still working" signal. Users see two truths.

Both are reachable with focused, low-risk changes.

## Root causes (grounded in code)

| Bug | File:line | Current | Required |
|---|---|---|---|
| B35a | `backend/opensec/integrations/github_app/client.py:316-` `check_repo_push_access` | Asks GitHub for the user's repo permissions; trusts `permissions.push=true` | Also consult the App's INSTALLATION permissions for the target repo via `GET /repos/{owner}/{repo}/installation` → look up the installation_id → check the installation's `permissions.contents == "write"`. If user says push=true BUT installation says contents != "write", return `can_push=False` with a specific "org admin needs to approve the App's newer permissions" message |
| B35b | `frontend/src/components/issues/IssueSidePanel.tsx` (top widget + status pill logic — grep for `stage` derivation) | Derives stage from the *latest agent run's status* only. When executor `status=completed` with `error_details`, that derivation lands on a "completed → success / next stage starts" path instead of "completed → terminal error" | Derive `stage` with a terminal-error branch: if the most recent run is `remediation_executor` AND has `structured_output.error_details`, stage becomes `executor_failed`. Header renders "Needs attention" pill (warning color) + "Push to GitHub failed — see activity log" widget; bottom "Cancel run" becomes "Retry" |

## Files touched

Backend (V2):
- `backend/opensec/integrations/github_app/client.py` — extend `check_repo_push_access`:
  - First call `GET /repos/{owner}/{repo}/installation` to find the installation_id covering this repo
  - Inspect the response's `permissions.contents` field
  - If `contents != "write"`, return `can_push=False` with message about org admin approval of new App perms
  - Falls back to the existing user-permissions check if the `/installation` call is unavailable (e.g., user token doesn't expose it)
- `backend/opensec/api/routes/agent_execution.py` — no behavior change; the preflight call itself stays the same, just gets a smarter `check_repo_push_access` underneath
- `backend/tests/integrations/test_github_app_client.py` — add three cases: install perms with contents:write → can_push, install perms with contents:read → can_push=False with the org-admin message, install lookup fails → fall back to old check

Frontend (V2):
- `frontend/src/components/issues/IssueSidePanel.tsx` — extend the stage-derivation hook (likely `useStage` or inline reducer — grep for `'planning' | 'plan_ready' | 'generating_fix'`):
  - Add `'executor_failed'` to the stage union
  - When `latestRun.agent_type === 'remediation_executor' && latestRun.status === 'completed' && errorDetailsOf(latestRun) != null`, return `'executor_failed'`
  - Update the header pill rendering: `executor_failed` → warning-tinted pill "Needs attention"
  - Update the top widget: `executor_failed` → "Push to GitHub failed — see activity log" (no spinner)
  - Update bottom button: `executor_failed` → "Retry" (fires same approve-then-execute chain as the plan_ready button)
- `frontend/src/components/issues/__tests__/IssueSidePanel.test.tsx` — add stage transition test

## Test plan (TDD-first)

Backend (pytest):
- `test_github_app_client.py::test_check_uses_install_perms_when_user_says_push_true_but_install_contents_read` — mock `/repos/{}/{}` returning user push=true, `/repos/{}/{}/installation` returning install perms with contents=read. Assert `can_push=False` and reason mentions "org admin needs to approve".
- `test_github_app_client.py::test_check_falls_back_when_install_lookup_unavailable` — mock `/installation` returning 404. Assert behavior matches pre-W3 (user perms only).
- `test_routes_agent_execution.py::test_executor_blocked_when_install_perms_insufficient` — end-to-end via FastAPI test client: POST `/agents/remediation_executor/execute` returns 412 when install perms are insufficient.

Frontend (Vitest):
- `IssueSidePanel.test.tsx::test_renders_executor_failed_stage_when_error_details_present` — mock agent runs with executor.status=completed + error_details, assert pill text and bottom button label
- `IssueSidePanel.test.tsx::test_retry_button_fires_approve_then_execute` — assert click chains the same mutation as the plan_ready Approve button

E2E (manual, Wave 3 QA):
- Trigger the same flow that failed in Wave 2: Approve & generate fix → executor runs → push fails. Verify:
  - Preflight blocks BEFORE executor runs (no 4-minute wait), returns 412 with structured detail
  - If somehow the executor does run and fails, the UI header transitions to "Needs attention" within 5 s + "Retry" button appears at bottom

## Risks

- **`/repos/{owner}/{repo}/installation` endpoint may not be callable with user OAuth tokens.** GitHub docs are unclear — some App endpoints require App JWT (signed with the App's private key). If user token returns 403, the fallback to the old check kicks in (no regression) but B35a stays unfixed. Mitigation: verify endpoint accessibility in a quick spike before merging. If user token can't call it, fall back to: mint an installation token using the App private key (deferred — needs IMPL-0019 ADR work) OR add a runtime probe (push a scratch ref, revert).
- **"Retry" button could double-trigger if the user spam-clicks.** Mitigation: disable while mutation pending (the existing pattern from PR #169's chained mutation).
- **Terminal-error stage in the side panel might be reached for *non-push* failures too** (any agent error_details). That's actually desirable — but make sure the messaging stays generic ("agent reported an error") so it doesn't mislabel non-push failures as push failures.

## Rollout

Single PR, 3 commits:
1. `fix(q01r-w2-preflight): consult App installation perms, not just user perms (B35a)`
2. `fix(q01r-w2-ui): executor_failed stage with Needs-attention header + Retry (B35b)`
3. `test(q01r-w2): regression tests for preflight + stage derivation`

Target branch: `main`.
