# IMPL-0014: Q01R — GitHub push-token preflight + App permission docs

**ADR:** [docs/adr/0037-github-app-write-permissions.md](../../adr/0037-github-app-write-permissions.md)
**Scope:** Wave 1.5 (Q01R) bug fix
**Bug:** B30 (P0)
**Owner:** App Builder (V2) — `backend/opensec/integrations/github_app/` + `backend/opensec/api/routes/`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

The Q01R QA found that the GitHub App device-flow user token can't push to org repos because `opensec-local-test`'s declared permissions don't include `Contents:write`. Per ADR-0037, we keep the user-OAuth-token architecture and fix the App permissions instead.

The code fix is a single preflight check that runs once after install (and again before the executor triggers): query GitHub for the user's effective permissions on the target repo via the current token. If `push: false` or `pull: false`, surface a clear error with a remediation link before the executor runs and silently produces an unpushable branch.

There are also two ops/docs tasks:

1. Update the dev `opensec-local-test` App on GitHub.com with the right permission matrix (manual GitHub admin action — outside code).
2. Document the required permission matrix in the OSS install guide.

## Root cause (grounded)

| Where | What | Required change |
|---|---|---|
| GitHub App `opensec-local-test` (and any prod App / user-created App) | Declares only `Contents:read` (or insufficient subset) | Manual GitHub config: add `Contents:write`, `Pull requests:write`, `Actions:read`, `Administration:read` per ADR-0037 |
| `backend/opensec/api/routes/workspaces.py:104-105` `_resolve_repo_env_vars()` | Injects `GH_TOKEN` from vault with no permission verification | Add a preflight that calls `GET /repos/{owner}/{repo}` with the token and inspects `permissions.push` |
| `backend/opensec/agents/executor.py:668-669` | Passes token to template assuming it works | (no change — preflight gates execution) |
| `frontend/src/components/issues/IssueSidePanel.tsx` | If executor structured-output reports `error_details`, side panel doesn't surface them (stays on "Thinking…" — see B28) | Render an error state when `agent_run.structured_output.error_details` is non-null; show the message + a "Fix my App permissions" link |

## Files touched

Backend:
- `backend/opensec/integrations/github_app/client.py` — add `check_repo_push_access(token, owner, repo) -> {can_push: bool, reason: str}` using `GET /repos/{owner}/{repo}` and inspecting the `permissions.push` field on the response (which reflects the effective token perms for that repo)
- `backend/opensec/api/routes/workspaces.py` — call the preflight in `_resolve_repo_env_vars()` or at the executor-trigger entry point; raise a structured 412 Precondition Failed if push is not allowed
- `backend/opensec/api/routes/_engine_dep.py` (or wherever executor triggering happens) — same preflight gate

Frontend:
- `frontend/src/components/issues/IssueSidePanel.tsx` — render `agent_run.structured_output.error_details` as an inline error state with a "How to fix" link
- `frontend/src/components/ai-provider/` — also surface permission errors during onboarding if we ever detect them earlier (nice-to-have)

Docs:
- `docs/guides/setup-github-app.md` (new or amend) — required permission matrix from ADR-0037; screenshot of the GitHub UI; troubleshooting section for the "Permission denied" symptom

Ops (manual, outside code):
- Update `opensec-local-test` permissions on GitHub.com. Doesn't require a PR — this is a config change. Once done, existing installations get a "Review new permissions" banner.

## Test plan (TDD-first)

Unit (backend, pytest):
- `test_github_app_client.py` — `check_repo_push_access` parses `permissions.push: true` as can-push, `false` as cannot, missing as cannot
- `test_routes_workspaces.py` — when token has no push, the workspace-creation or executor-trigger route returns 412 with a structured detail body identifying "github_app_permissions" as the failed precondition

Unit (frontend, Vitest):
- `IssueSidePanel.test.tsx` — when an agent run has `error_details`, the panel renders the error message and the "How to fix" link

E2E (manual, captured by Wave-2 Q01 re-run):
- With the App configured correctly: open a Critical finding, run plan, click Approve & generate fix, verify the executor actually pushes and a draft PR is created on GitHub
- With the App misconfigured (revert permissions): same flow, verify a clear in-UI error appears before the executor wastes a run on unpushable changes

## Risks

- **Preflight adds one GitHub API call per executor trigger.** Mitigation: negligible cost; cache result per (token, repo) for the workspace's lifetime if needed.
- **`permissions.push` in the `/repos/...` response is the *effective* push perm for the token. Confirm GitHub returns this on user-to-server requests.** Per GitHub docs, yes — the `permissions` block on the repo response reflects the authenticated principal's effective perms. Verify with a manual smoke test before merging.
- **Existing users of the dev App see a "Review new permissions" banner on next install.** That's expected, but we should call it out in the PR description.

## Rollout

1. Update App permissions on GitHub.com (manual, can happen before or with the PR — preflight is forward-compatible).
2. Land the PR (`fix(q01r-github-app):`) into `main`.
3. Wave 2 re-runs Q01 against the merged build.

## Follow-up BACKLOG items (separate work)

- Re-evaluate user-OAuth-token vs installation-token after we have a use case for non-user-bound execution (e.g., nightly re-assessments). Defer until needed; ADR-0037 documents the decision and the alternative.
