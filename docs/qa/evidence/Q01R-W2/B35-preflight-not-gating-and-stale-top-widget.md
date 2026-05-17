# Q01R-W2-B35 — Executor preflight didn't gate; top widget stays "Pushing branch" past terminal error

**Severity:** P1
**Surface:** backend (preflight wiring) + UI (panel header reactivity)

## What I observed
On the fresh wave-2 build, I drove a minimist Critical through plan → "Approve & generate fix" → executor. The executor ran for 4m 28s and exited with `status: completed` but `structured_output.error_details` populated:

> Unable to push branch to remote: The GitHub token (galanko user) lacks write access to cliff-security/NodeGoat repository.

**Two layered bugs:**

### B35a — preflight not gating (regression in PR #168 wiring)
PR #168 added `check_repo_push_access()` and a 412 gate in `agent_execution.py:execute_agent`. The intent was: before triggering the `remediation_executor` agent, call this preflight; if can_push=false, refuse with 412 and never burn ~4 min running an executor that can't ship.

In wave-2 the executor RAN to completion despite the same push failure that the preflight should have caught. No "412" or "github_app_permissions" appears in the docker logs.

Either:
- the UI route to invoke the executor doesn't go through `agent_execution.py:execute_agent`, OR
- the preflight is wired but its `can_push` check returns true (false positive) for this token+repo combination

### B35b — top-widget UI stays "Pushing branch / Thinking…" past terminal error
The activity card correctly renders the error (PR #168's `ActivityRunErrorCard` works — error message + "How to fix" link both visible). But the side panel's TOP widget still says "Pushing the branch to GitHub… / We'll surface the result here when it's ready" and the status pill at top still reads "Pushing branch". The user gets two contradictory signals.

Root cause hint: the top widget's stage-detection logic doesn't transition when the executor `status === 'completed'` AND `structured_output.error_details` is non-null. It probably treats the executor's structured_output.status=`needs_approval` as "still working" rather than "terminal error".

### B35c — actual push failure (the original B30 root cause is still alive)
Beyond the preflight + UI, the push itself fails. Possible causes:
- The App installation on cliff-security may not have approved the newer `contents:write` permission (org admin approval gate). The App's declared perms include it, but the per-install permission set may still be the pre-Q5 subset.
- The user OAuth token from device flow only includes perms × repos where (App installed AND user has access). If the install on cliff-security is on user account (galanko) rather than org (cliff-security), the user token treats cliff-security repos as inaccessible.

Verification I couldn't do without the App private key: list `/app/installations/133175235` permissions to compare against ADR-0037.

## Recommended fixes

### Backend (B35a)
1. Audit which API routes actually trigger the executor (find every invocation of `executor.execute_agent` / `pipeline.run_agent`). Wire the preflight into ALL of them, not just `execute_agent` route.
2. Add an integration test in `backend/tests/test_routes_workspaces.py` that simulates clicking "Approve & generate fix" through the wave-1.5 chained mutation and asserts the preflight is consulted.

### UI (B35b)
1. When `agent_run.structured_output.error_details` is non-null AND `status === 'completed'`, the IssueSidePanel header should transition to "Needs your attention" (or similar) with the error badge — not stay on the in-progress "Pushing branch" state.
2. The bottom "Cancel run" button should become a "Retry" or "Mark resolved" action.

### Operational (B35c)
1. Document that re-installing the App or having the org admin approve new permissions is required after ADR-0037 perm changes ship to the prod App.
2. Add a `/api/integrations/github/diagnose` endpoint that calls `check_repo_push_access` on demand and returns a structured result the Settings page can show — so users can troubleshoot before clicking Approve.

## Evidence

Executor run `0b3b5169-f4f2-46e6-9205-e4b034854a6d` on workspace `8f174af5-eb9f-4aea-a72a-289b09526ea7`:
- `status: completed`
- `started_at: 2026-05-17T16:47:24Z`
- `completed_at: 2026-05-17T16:51:53Z` (4m 28s)
- `structured_output.status: needs_approval`
- `structured_output.error_details: "Unable to push branch..."`
- `next_action_hint: manual_push_and_pr_creation`

Local commit `8db22f0` on branch `opensec/fix/minimist-prototype-pollution` inside the container — never reached origin.
