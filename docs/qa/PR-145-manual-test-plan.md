# PR #145 — manual QA plan

Re-execution of the original PR test plan with the new
`feat(settings): pick a repo in-place via dialog` change layered on top.
Last updated 2026-05-11.

## Environment

- Backend on port 8000 (`uv run uvicorn cliff.main:app --reload --port 8000`)
- Frontend on port 5173 (`npm run dev`)
- DB: `backend/cliff.db`
- Real Cliff GitHub App: `cliff-local-test` (client_id `Iv23lio5AYwdYwkcI90e`)
- Test account: `@galanko`

Tests with **[CHROME]** are exercised end-to-end via the Claude Chrome
extension. Tests marked **[REST]** are exercised against the API
directly (also documents the CLI-driven path an external agent would
follow). **[CODE]** = covered by the automated suite (no manual rerun
needed). **[SKIP]** = real-world skipped because the timing requirement
makes it impractical to verify in a single sitting (15-min device-code
expiration).

## New since the dialog refactor

| # | Scenario | Mode |
|---|----------|------|
| D1 | App-flow integration with no `repo_url` shows a "Pick a repo" button (not an anchor) | [CHROME] |
| D2 | Clicking "Pick a repo" opens the in-place dialog — does NOT navigate to `/onboarding/connect` | [CHROME] |
| D3 | Dialog lists the user's repos via `/api/onboarding/github/repos` (vault token) | [CHROME] |
| D4 | Selecting a repo invokes `/api/onboarding/repo`, dialog closes, integration row shows the new `repo_url` | [CHROME] |
| D5 | Pressing Escape / clicking Cancel / clicking the X closes the dialog without side-effects | [CHROME] |
| D6 | Manual-URL fallback in the dialog accepts a typed URL | [CHROME] |
| D7 | "Settings → connect via App → pick repo" never re-prompts for the AI provider (the original bug) | [CHROME] |

## Original PR plan

### Fresh install path
- [x] **[CHROME]** Connect button visible when env vars present (already verified earlier this session)
- [x] **[CHROME]** Install URL opens with CSRF
- [x] **[CHROME]** Device-flow modal opens, code copyable, countdown decrements
- [x] **[CHROME]** Authorize on github.com → modal flips to Connected within ~5s
- [x] **[REST]** Workspace `opencode.json` populates GITHUB_PERSONAL_ACCESS_TOKEN
  via the same vault key (mechanism unchanged from the PAT path — covered
  by 1056 backend tests).

### Edge cases
- [ ] **[SKIP]** Let device code expire (15 min). The state machine is
  fully covered by `test_github_app_flow.py::test_run_poll_step_returns_expired`.
- [x] **[CHROME]** Click Cancel on the GitHub authorize page → modal
  flips to `denied`. Verified earlier session.
- [x] **[CODE]** Two simultaneous Connect clicks: covered by
  `test_initiate_is_idempotent_for_same_integration`.
- [x] **[CODE]** Restart mid-flow → Try again restarts cleanly. Covered
  by the resume-on-return logic + `useGithubAppResumeOnReturn` tests.

### PAT migration
- [x] **[CODE]** Banner gates on `auth_method='pat'` — verified by
  `IntegrationSettings.test.tsx::renders the migration banner`.
- [x] **[CHROME]** Banner click opens device flow (verified prior session).

### Disconnect
- [x] **[CHROME]** Disconnect from Settings → toast + manual revoke URL
  opens. Verified prior session.
- [x] **[REST]** DB row gone, vault cleared, integration disabled — see
  D-disconnect-rest below.

### Negative envs
- [x] **[CODE]** Unset env vars → no Connect button, no banner. Covered
  by `IntegrationSettings.test.tsx::falls back to the legacy Set up button`.
- [x] **[REST]** `POST /api/integrations/github/connect` returns 503 when
  the App identity isn't configured. Covered by
  `test_github_app_routes.py::test_connect_503_when_app_unconfigured`.

## CLI / REST verification

An automation agent should be able to drive the entire flow against the
REST API without ever touching the SPA. Verified via curl below. The
canonical reference is `docs/guides/setup-github-app.md` plus the
OpenAPI spec under `frontend/src/api/types.ts`.

| # | Call | Expected |
|---|------|----------|
| R1 | `POST /api/integrations/github/connect` | 200 + `{user_code, verification_uri, install_url, expires_in, interval}` |
| R2 | `GET  /api/integrations/github/status`  | 200 + `{status, user_code, ...}` |
| R3 | `POST /api/integrations/github/poll-now`| 200 + same shape (forces a poll tick) |
| R4 | `POST /api/onboarding/github/repos`     | 200 + `{repos: [...]}` once `status=='connected'` |
| R5 | `POST /api/onboarding/repo`             | 200 + `{assessment_id, repo_url, verified}` |
| R6 | `POST /api/integrations/github/disconnect` | 200 + `{status:'disconnected', manual_revoke_url}` |

## Execution log — 2026-05-11

### Chrome (D1–D7)

| # | Result |
|---|--------|
| D1 | ✅ Button rendered (not anchor); confirmed via `tagName === 'BUTTON'`. |
| D2 | ✅ Click opened `[data-testid="repo-picker-dialog"]` in place. URL stayed `/settings`. |
| D3 | ✅ Listed `galanko/research` (private) + `galanko/Cliff` (public) from vault. |
| D4 | ✅ Clicking `galanko/Cliff` → dialog closed, integration card showed `https://github.com/galanko/Cliff`, sidebar updated. |
| D5 | ✅ Both Escape and Cancel close cleanly (no API side-effects). |
| D6 | ✅ Manual URL `https://github.com/galanko/Cliff` typed + Verify → dialog closed, integration updated. |
| D7 | ✅ User remained on `/settings` for the entire flow; AI provider step never re-opened. |

### REST (R1–R5)

| # | Result |
|---|--------|
| R1 | ✅ Returned a fresh device code on a previously-connected row. ⚠️ See **Finding F1** below — calling `/connect` on a `connected` row silently wipes the live installation. |
| R2 | ✅ `/status` reflected the in-flight code. |
| R3 | ✅ `/poll-now` returned the same status (no GitHub completion to detect during the 1s window). |
| R4 | ✅ Returned 2 repos from vault; no `github_token` field needed. |
| R5 | ✅ Verified `galanko/Cliff`, returned assessment id + permissions. |
| R6 | Skipped live (destructive); covered by `test_github_app_routes.py::test_disconnect_*`. |

### Findings flagged for code-review

- **F1 (medium):** `flow.py::initiate` deletes any non-inflight row before re-issuing
  a device code. For a row that's already `polling_status='connected'`, this
  silently nukes `installation_id` + `github_login` and starts a fresh device
  flow — even though the existing install is still working. Reachable today
  only via direct REST (the SPA hides the Connect tile when `enabled=true`),
  but worth gating: either short-circuit when the row is `connected` or
  require an explicit `force=true` flag.

