# IMPL-0010: GitHub App + Device Flow onboarding

**ADR:** [docs/adr/0035-github-app-device-flow-onboarding.md](../../adr/0035-github-app-device-flow-onboarding.md)
**Status:** Draft (awaiting CEO approval)
**Date:** 2026-05-07
**Owning team:** App Builder (V2). No agent code changes.

## Summary

Replace the PAT-only GitHub onboarding with a shared GitHub App + Device
Flow. New users click **Connect GitHub** → install on github.com →
authorize this device with an 8-character code → connected. Existing
PAT users continue to work and see a one-line "switch to the App"
banner.

Implementation is **backend-heavy** but **architecturally minimal** —
all token storage rides the existing credential vault, the token plugs
into the same MCP Gateway placeholder the PAT used, and the only new
persistent state is one small table to track per-installation metadata.
No new encryption module, no new key resolution chain.

## Architectural anchors

- **Token storage:** Reuse `backend/cliff/integrations/vault.py`
  (ADR-0016). Store the user access token under the existing
  `github_personal_access_token` credential key so the MCP Gateway
  injection (ADR-0018) keeps working unchanged. Refresh token (if
  present) lives under a new key `github_refresh_token` on the same
  integration row.
- **Registry:** Keep the single `github` registry entry
  (`backend/cliff/integrations/registry/github.json`) unchanged. The
  MCP server doesn't care whether the bearer is a PAT or a user access
  token — both work in `Authorization: Bearer <token>`.
- **Persistent metadata:** One new table,
  `github_app_installation`, holds installation_id, CSRF state,
  in-flight device-code metadata, polling status, token expiry, and
  GitHub login. No secrets in this table; secrets stay in the vault.
- **Server-side polling:** A short-lived asyncio task per in-flight
  device flow polls `https://github.com/login/oauth/access_token`
  every `interval` seconds and writes the result into
  `github_app_installation`. Frontend polls our `/status` endpoint;
  our backend never asks the frontend to do the GitHub poll.
- **No JWT, no installation tokens.** We use *user access tokens* (the
  output of the device flow), not App authentication. JWT signing
  belongs to SaaS; it's deliberately absent here.

## File-level scope

**New files (backend):**

- `backend/cliff/integrations/github_app/` — module dir
  - `__init__.py`
  - `client.py` — `GitHubDeviceFlowClient`: thin wrapper around
    GitHub's three endpoints (`/login/device/code`,
    `/login/oauth/access_token`, `/user`). Uses `httpx`. Stateless.
  - `flow.py` — `DeviceFlowOrchestrator`: state machine, polling task,
    DB writes. Owns the in-flight lifecycle.
  - `repo.py` — `github_app_installation` CRUD (`create_pending`,
    `attach_installation_id`, `mark_connected`, `mark_failed`,
    `get_inflight`, `get_for_integration`, `delete`).
- `backend/cliff/api/routes/github_app.py` — four endpoints
  (`connect`, `setup`, `status`, `disconnect`). Mounted at
  `/api/integrations/github` from `backend/cliff/main.py`.
- `backend/cliff/db/migrations/016_github_app_installation.sql` —
  schema migration.

**New files (frontend):**

- `frontend/src/components/settings/GithubAppConnectButton.tsx` —
  triggers `/connect`, opens install URL.
- `frontend/src/components/settings/GithubAppDeviceFlowModal.tsx` —
  user code display, copy button, countdown, polling, error states.
- `frontend/src/components/settings/GithubAppMigrationBanner.tsx` —
  one-line banner shown when an active PAT integration exists.
- `frontend/src/api/githubApp.ts` — typed client for the four routes,
  TanStack Query hooks (`useGithubAppConnect`,
  `useGithubAppStatus`, `useGithubAppDisconnect`).

**Modified files (backend):**

- `backend/cliff/main.py` — register the new router.
- `backend/cliff/config.py` — add `CLIFF_GITHUB_APP_CLIENT_ID`,
  `CLIFF_GITHUB_APP_SLUG`, `CLIFF_BASE_URL` settings (the latter
  may already exist; verify and reuse).
- `backend/cliff/api/routes/settings.py` — add a single field to the
  integration list response per row indicating whether GitHub App
  onboarding is available (just a boolean derived from
  `settings.github_app_client_id is not None`). No other changes — PAT
  CRUD stays.

**Modified files (frontend):**

- `frontend/src/components/settings/IntegrationSettings.tsx` —
  branch in the GitHub row: if `github_app_available` and not yet
  connected via App, show `GithubAppConnectButton` above (or in place
  of) the PAT form. If connected via PAT, show
  `GithubAppMigrationBanner` above the existing PAT-connected card.
  No changes to the PAT form itself.

**No changes** to `backend/cliff/integrations/vault.py`,
`backend/cliff/integrations/gateway.py`,
`backend/cliff/integrations/registry/github.json`,
`backend/cliff/assessment/posture/github_client.py`, or any agent
template.

## Backend route contracts

All routes mounted under `/api/integrations/github`. Authentication
piggybacks on the same single-user session pattern the rest of the API
uses. Errors follow the existing `{ "detail": "..." }` FastAPI shape.

### `POST /connect`

Initiates the device flow. Idempotent: if an in-flight row exists for
the singleton GitHub-App integration, returns its current state instead
of starting a new one.

**Request body:** `{}` (none).

**Behavior:**

1. If `CLIFF_GITHUB_APP_CLIENT_ID` is not set → 503 with explanatory
   detail.
2. Look up the (singleton) GitHub-App `integration_config` row. Create
   it disabled if missing.
3. Look up the matching `github_app_installation` row. If one exists
   with a non-expired in-flight device code → return its existing
   `user_code` etc. without re-issuing. (Avoids GitHub rate-limiting on
   refresh.)
4. Otherwise, call `POST https://github.com/login/device/code` with
   `client_id` and (optionally) `scope` empty.
5. Generate `csrf_state` (32-byte URL-safe token) and store
   `(integration_id, csrf_state, device_code [encrypted via vault],
   user_code, verification_uri, expires_at, interval, polling_status =
   "pending")`.
6. Spawn an asyncio polling task for the device_code lifetime.
7. Return:

   ```json
   {
     "user_code": "MNPQ-RSTU",
     "verification_uri": "https://github.com/login/device",
     "expires_in": 900,
     "interval": 5,
     "install_url": "https://github.com/apps/{slug}/installations/new?state=<csrf>"
   }
   ```

### `GET /setup`

Landing page after `Install` on github.com. Called by the browser
after GitHub redirects to the App's `setup_url`. Validates CSRF, stores
the `installation_id`, and bounces the user back to the frontend.

**Query params:** `installation_id` (int), `setup_action` ("install" or
"update"), `state` (the CSRF token we issued in `/connect`).

**Behavior:**

1. Look up `github_app_installation` by `csrf_state == state`. If not
   found → redirect to `/integrations?github_setup=error&reason=csrf`.
2. Update row with `installation_id`, `installation_completed_at = now`.
3. Redirect to
   `<frontend_base_url>/settings/integrations?github_setup=complete&integration_id=<id>`.

The poller continues running in the background regardless of whether
the user has authorized the device yet.

### `GET /status`

The frontend polls this every ~2s while the modal is open.

**Query params:** none (operates on the singleton in-flight install).

**Returns:**

```json
{
  "status": "pending" | "installation_pending" | "device_pending" | "connected" | "expired" | "denied" | "rate_limited" | "error",
  "user_code": "MNPQ-RSTU",
  "expires_at": 1746690000,
  "installation_id": 1234567,
  "github_login": "octocat",
  "error": "<human-readable error or null>"
}
```

State definitions (the poller writes these into
`github_app_installation.polling_status`):

| Status | Meaning |
|--------|---------|
| `installation_pending` | Device code issued, app not yet installed (no `installation_id` on row) |
| `device_pending` | App installed, device authorization pending |
| `connected` | Token received and stored. UI can dismiss the modal. |
| `expired` | The device code expired before the user authorized. UI should let them retry. |
| `denied` | User clicked Cancel on the device authorization page. |
| `rate_limited` | Slowed to longer interval due to `slow_down`. UI keeps spinning. |
| `error` | Unexpected error from GitHub. Message in `error`. |

### `POST /disconnect`

Hard-revokes locally; does **not** revoke on GitHub (we don't have the
`client_secret`).

**Behavior:**

1. Cancel any in-flight polling task.
2. Delete `github_personal_access_token` and `github_refresh_token`
   credentials from the vault for the GitHub-App integration row.
3. Delete the `github_app_installation` row.
4. Set the `integration_config.enabled = False` (so the gateway stops
   resolving it).
5. Return:

   ```json
   {
     "status": "disconnected",
     "manual_revoke_url": "https://github.com/settings/applications"
   }
   ```

The frontend shows the manual revoke URL in a toast.

## Schema migration

`backend/cliff/db/migrations/016_github_app_installation.sql`:

```sql
-- Track per-installation state for the GitHub App device flow (ADR-0035).
-- All secrets remain in the credential vault — this table holds non-secret
-- metadata plus encrypted in-flight device codes (encryption supplied by
-- the existing vault module via store/retrieve).

CREATE TABLE IF NOT EXISTS github_app_installation (
    id              TEXT PRIMARY KEY,
    integration_id  TEXT NOT NULL UNIQUE
                    REFERENCES integration_config(id) ON DELETE CASCADE,

    -- App identity at time of install (snapshot for support).
    app_slug        TEXT NOT NULL,
    client_id       TEXT NOT NULL,

    -- GitHub-issued installation ID (set after /setup callback).
    installation_id INTEGER,
    installation_completed_at INTEGER,

    -- CSRF token bound to the install URL we generated. Validated on /setup.
    csrf_state      TEXT NOT NULL UNIQUE,

    -- In-flight device code metadata (cleared once status is terminal).
    user_code            TEXT,
    verification_uri     TEXT,
    device_code_expires_at INTEGER,
    polling_interval_seconds INTEGER,

    -- Current state of the polling state machine.
    polling_status   TEXT NOT NULL DEFAULT 'installation_pending'
                     CHECK (polling_status IN (
                         'installation_pending',
                         'device_pending',
                         'connected',
                         'expired',
                         'denied',
                         'rate_limited',
                         'error'
                     )),
    polling_error    TEXT,
    last_polled_at   INTEGER,

    -- Token lifetime (nullable — present only when token expiry is enabled
    -- on the App). Token itself lives in the credential vault.
    token_expires_at INTEGER,

    -- Identity of the user who authorized (populated post-connect via /user).
    github_login     TEXT,

    -- Last successful validation against GitHub (e.g. via GET /user).
    last_validated_at INTEGER,

    connected_at     INTEGER,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_github_app_installation_csrf
    ON github_app_installation(csrf_state);
```

Notes:

- `id` is a UUID4 generated app-side (matches existing convention in
  `integration_config`).
- The `device_code` itself is **never** stored in this table —
  `vault.store(integration_id, "github_device_code", device_code)`
  encrypts it. On terminal state we delete it via
  `vault.delete(integration_id, "github_device_code")`.
- `ON DELETE CASCADE` on `integration_id` keeps cleanup automatic when
  the integration row is deleted via existing routes.
- ADR-0033 (pre-alpha destructive migrations) still applies — schema
  changes are non-additive only when needed; this one is purely
  additive.

## Token-flow integration with the MCP Gateway

The MCP Gateway resolves
`${credential:github_personal_access_token}` from the credential vault
when generating each workspace's `opencode.json` (see
`backend/cliff/integrations/gateway.py`). It looks up credentials by
`(integration_id, key_name)` and substitutes them into the `env` block
of the GitHub MCP server config.

For the new flow, after `connect` succeeds:

```python
await vault.store(
    integration_id=gh_app_integration.id,
    key_name="github_personal_access_token",  # same key as PAT
    plaintext=user_access_token,
)
if refresh_token:
    await vault.store(
        integration_id=gh_app_integration.id,
        key_name="github_refresh_token",
        plaintext=refresh_token,
    )
await repo_integration.set_enabled(integration_id, True)
```

**Result:** The next time a workspace starts, the gateway resolves
`${credential:github_personal_access_token}` to the user access token
instead of a PAT. The agent code, the GitHub MCP server, the
`github_client.py` posture client — none of them change.

For PAT users on the same instance, their PAT integration row has its
own `integration_id` and its own `github_personal_access_token`
credential; the new App flow uses a **different** integration row, so
the two cannot collide. (When the PAT user upgrades, we mark the PAT
row `enabled=False` after the new App row connects.)

## Server-side polling state machine

A single asyncio task per in-flight device flow. Spawned at `/connect`,
cancelled at `/disconnect` or on terminal state. Implemented in
`flow.py`:

```text
state := installation_pending
loop forever:
    if device_code_expires_at < now: state := expired; break
    sleep(interval)

    response := GitHub.poll_token(client_id, device_code)

    match response:
        case {access_token, refresh_token?, expires_in?}:
            store credentials in vault
            mark integration enabled
            optionally fetch GET /user → github_login, last_validated_at
            state := connected; break
        case {error: "authorization_pending"}:
            # device_pending if installation_id is set, else installation_pending
            state := device_pending if has_installation_id else installation_pending
        case {error: "slow_down"}:
            interval += 5
            state := rate_limited (transient — back to pending next tick)
        case {error: "expired_token"}:
            state := expired; break
        case {error: "access_denied"}:
            state := denied; break
        case <unexpected error>:
            polling_error := str(e)
            state := error; break
```

State transitions are persisted on every iteration so `/status` always
reflects the latest. The task is **fire-and-forget** — if the process
restarts, the in-flight device code expires naturally; the user just
clicks Connect again. No durable task queue. (Acceptable because the
window is 15 minutes max, and Cliff is single-user.)

To support process restart gracefully, `/connect` checks for an
existing non-terminal `github_app_installation` row before issuing a
new device code; if found, it just re-spawns the polling task for the
existing row. No double-issue.

## Token refresh

If `CLIFF_GITHUB_APP_USER_TOKENS_EXPIRE` is true (or the device-flow
response includes an `expires_in`), refresh handling activates:

- Add a `refresh_user_access_token(integration_id)` helper that calls
  `POST /login/oauth/access_token` with
  `grant_type=refresh_token` and the stored refresh token, then
  re-stores both tokens.
- Add a one-shot retry hook on 401 responses from
  `assessment/posture/github_client.py` (the only consumer in V1):
  catch 401 → call refresh → retry once → if still 401, mark
  `polling_status = "error"`, `polling_error = "needs_reconnect"` so
  the UI surfaces "reconnect required."
- The MCP server (npx-spawned) doesn't have a refresh hook today.
  When tokens expire under it, the workspace will start failing GitHub
  calls; the user reconnects. Document this V1 behavior in the setup
  guide. (Mitigation: recommend non-expiring user tokens on the App
  config — the default we ship.)

## Frontend state machine + UX

States for the `IntegrationSettings` GitHub card:

```text
disconnected (no integration row)
  └ click "Connect GitHub"
       → POST /connect → state := installing
installing (waiting for /setup callback)
  └ frontend opens install_url in new tab
  └ frontend polls /status: status=installation_pending
  └ on URL ?github_setup=complete OR status=device_pending
       → state := authorizing (open modal)
authorizing (modal open)
  └ frontend polls /status every 2s
  └ shows user_code, copy button, countdown, "Open authorize page" btn
  └ on status=connected → state := connected, dismiss modal, toast success
  └ on status=expired/denied/error → show error in modal, "Try again" btn
connected
  └ shows green "Connected as <github_login>"
  └ "Disconnect" button → POST /disconnect → state := disconnected
error
  └ shows specific error, "Try again" → state := disconnected
```

Modal countdown matches `expires_at` from `/status`. At 0:00 the modal
auto-flips to expired state.

PAT-connected users see `GithubAppMigrationBanner` above the existing
PAT card. Clicking it triggers the same `/connect` flow; on success,
the App becomes the active GitHub integration and a toast confirms
"GitHub App connected. The old PAT integration has been archived; you
can remove it anytime from this page."

## PAT migration (feature flag + archive, no deletion)

The flag is **runtime, env-driven, no DB**: `CLIFF_GITHUB_APP_CLIENT_ID`
unset → only PAT visible (today's behavior). Set → both visible, App
promoted as primary CTA.

Migration step (server-side, on a successful App `/connect`):

1. Find any other enabled `integration_config` row with
   `provider_name == "github"` and a different ID (the PAT row).
2. Set its `enabled = False`.
3. Emit audit event `github_app.pat_archived`.
4. **Do not** delete the PAT credential — the user may want to roll
   back. The "Disconnect" button on the archived PAT row deletes its
   credential explicitly (existing PAT path; no new code).

This is intentionally minimal: one boolean flip, audit event, no
schema change to `integration_config`. We do not rename, copy, or
re-key anything. The PAT row keeps its own `integration_id` and its
own credentials, fully separate from the App row.

## Test plan (TDD-first)

**All tests written before implementation.** Lint (`ruff`) + type
hygiene + ESLint (frontend) green before opening the PR.

### Backend unit tests (mock GitHub via httpx)

- `tests/test_github_app_client.py`
  - `test_request_device_code_returns_parsed_payload`
  - `test_request_device_code_handles_429_rate_limit`
  - `test_poll_token_returns_access_token_on_success`
  - `test_poll_token_returns_pending_status_when_authorization_pending`
  - `test_poll_token_returns_slow_down_when_rate_limited`
  - `test_poll_token_returns_expired_when_token_expired`
  - `test_poll_token_returns_denied_on_access_denied`
  - `test_poll_token_raises_on_unknown_github_error`

- `tests/test_github_app_flow.py` (state machine — uses fake clock)
  - `test_initial_state_is_installation_pending`
  - `test_setup_callback_validates_csrf`
  - `test_setup_callback_rejects_unknown_state`
  - `test_setup_callback_advances_to_device_pending`
  - `test_polling_loop_advances_to_connected_on_token`
  - `test_polling_loop_stores_token_in_vault_under_correct_key`
  - `test_polling_loop_stores_refresh_token_when_present`
  - `test_polling_loop_advances_to_expired_after_device_code_expiry`
  - `test_polling_loop_advances_to_denied_on_access_denied`
  - `test_polling_loop_increments_interval_on_slow_down`
  - `test_polling_loop_marks_error_on_unexpected_failure`
  - `test_disconnect_cancels_in_flight_poller`
  - `test_disconnect_clears_credentials_and_installation_row`
  - `test_pat_row_archived_after_app_connect`

- `tests/test_github_app_routes.py` (FastAPI TestClient)
  - `test_connect_returns_503_when_client_id_unset`
  - `test_connect_returns_user_code_and_install_url`
  - `test_connect_idempotent_for_existing_inflight`
  - `test_setup_validates_csrf_and_redirects_with_complete_flag`
  - `test_setup_redirects_with_error_on_csrf_mismatch`
  - `test_status_reports_each_state_correctly`
  - `test_disconnect_clears_state_and_returns_manual_revoke_url`

- `tests/test_github_app_token_refresh.py`
  - `test_refresh_swaps_token_under_same_credential_key`
  - `test_refresh_failure_marks_integration_needs_reconnect`

- `tests/test_github_app_gateway_integration.py` (touches existing
  gateway path)
  - `test_user_access_token_resolves_through_existing_placeholder`
  - `test_pat_and_app_rows_dont_collide_when_only_app_enabled`

### Frontend unit tests (Vitest + React Testing Library)

- `GithubAppDeviceFlowModal.test.tsx`
  - renders user code, copy button, countdown
  - polls `/status` and dismisses on `connected`
  - shows expired state when `expires_at` passes
  - shows denied state on `denied`
  - "Try again" calls `/disconnect` then `/connect`
- `GithubAppMigrationBanner.test.tsx`
  - shows for active PAT integration when App available
  - hidden when App unavailable or already on App
  - click triggers `/connect`
- `IntegrationSettings.test.tsx`
  - GitHub row branches on `github_app_available`
  - existing PAT-only behavior preserved when App unavailable

### Manual QA checklist (CI can't simulate)

These steps require a real GitHub account and the registered Cliff App.

1. **Fresh install path.**
   - [ ] Set `CLIFF_GITHUB_APP_CLIENT_ID` and
     `CLIFF_GITHUB_APP_SLUG` in `.env`. Restart.
   - [ ] Open Integrations page. GitHub row shows **Connect GitHub**.
   - [ ] Click. Verify a new tab opens to
     `https://github.com/apps/<slug>/installations/new?state=<csrf>`.
   - [ ] Pick a personal repo. Click Install.
   - [ ] GitHub redirects to `/api/integrations/github/setup` and
     bounces back to the Integrations page with
     `?github_setup=complete`.
   - [ ] Modal opens automatically. User code is large, copyable,
     countdown is decreasing.
   - [ ] Click **Open authorization page**. New tab opens to
     `https://github.com/login/device`.
   - [ ] Paste user code, click Authorize.
   - [ ] Within ~5s Cliff modal flips to "Connected as <login>",
     dismisses, GitHub row shows green connected state.
   - [ ] Open a workspace. Verify a workspace MCP config
     (`data/workspaces/<id>/opencode.json`) was generated with the
     `GITHUB_PERSONAL_ACCESS_TOKEN` env populated, and the GitHub MCP
     server starts cleanly. (`docker logs` or process logs.)

2. **Edge cases.**
   - [ ] Let the device code expire (15 min). Modal flips to
     "expired", "Try again" works.
   - [ ] On the GitHub auth page, click Cancel. Modal flips to
     "denied" within ~5s.
   - [ ] Close the modal mid-flow, re-open Integrations page. State is
     correctly recovered (modal re-opens at the same countdown).
   - [ ] Two simultaneous `/connect` calls (rapid double-click) don't
     issue two device codes — second returns the first's state.
   - [ ] Restart the Cliff process mid-flow. After restart,
     `/status` reports `error` or `expired` (acceptable). Click
     **Try again** — flow restarts cleanly.

3. **PAT migration.**
   - [ ] Start with an existing PAT integration connected.
   - [ ] Set the App env vars, restart. PAT row is still **Connected**.
     Banner appears: "Switch to the new GitHub App."
   - [ ] Click banner. Device flow modal opens. Complete it.
   - [ ] PAT integration row flips to **Archived**. App row is the
     active one. Workspaces use the App token automatically.
   - [ ] Open a workspace and verify GitHub MCP server still works.

4. **Disconnect.**
   - [ ] On a connected App integration, click **Disconnect**.
   - [ ] Toast surfaces the manual revoke URL
     (`github.com/settings/applications`).
   - [ ] DB: `github_app_installation` row gone, credentials gone,
     integration disabled.
   - [ ] Workspace MCP config regenerates without GitHub MCP server
     (or with stale token cleared, depending on freshness check).

5. **Negative envs.**
   - [ ] Unset `CLIFF_GITHUB_APP_CLIENT_ID`. Restart. UI shows the
     legacy PAT form only — no Connect button, no banner.
   - [ ] `POST /api/integrations/github/connect` returns 503 with a
     clear message.

## Phased rollout / task breakdown for `/app-builder`

Each phase ends with passing tests and (where applicable) a working UI
slice that can be demoed.

### Phase 1 — Schema + types (1–2 commits)

- Migration `016_github_app_installation.sql`.
- `repo.py` with CRUD functions, fully tested with the existing
  in-memory aiosqlite test fixture.
- Pydantic models: `GithubAppInstallation`, `DeviceFlowStatus` enum.

### Phase 2 — GitHub HTTP client (1 commit)

- `client.py` with three functions:
  `request_device_code`, `poll_token`, `fetch_user`.
- Backed by `httpx.AsyncClient`. All endpoints overridable for tests
  via a base URL setting (`CLIFF_GITHUB_API_BASE_URL`,
  `CLIFF_GITHUB_OAUTH_BASE_URL`).
- Unit tests covering every documented response shape from GitHub's
  Device Flow docs.

### Phase 3 — Orchestrator + state machine (2 commits)

- `flow.py` `DeviceFlowOrchestrator` with `start()`, `stop()`,
  `_poll_loop()` private. Uses fake clock + injected client in tests.
- Vault integration: stores access token under
  `github_personal_access_token`, refresh token under
  `github_refresh_token`. Tests verify exact key names.
- Audit-log emission for every state transition.

### Phase 4 — API routes (1 commit)

- `routes/github_app.py` with the four endpoints. Mount in
  `main.py`.
- TestClient tests for full route surface, including 503 when env
  unset, CSRF mismatch redirect, idempotent connect.
- `settings.py` adds the `github_app_available` boolean field to the
  GitHub registry row in the integration list response.

### Phase 5 — Token refresh wiring (1 commit)

- `refresh_user_access_token` helper.
- `github_client.py` (in `assessment/posture/`) — wrap its `_request`
  with a 401-retry hook. Tests with mocked 401 → refresh → 200.

### Phase 6 — Frontend (2–3 commits)

- `api/githubApp.ts` typed client + hooks.
- `GithubAppConnectButton` + tests.
- `GithubAppDeviceFlowModal` + tests (countdown, polling, error
  states).
- `GithubAppMigrationBanner` + tests.
- `IntegrationSettings.tsx` integration: branch on
  `github_app_available` and existing PAT presence.

### Phase 7 — Docs + QA (1 commit)

- `docs/guides/setup-github-app.md` — admin guide for registering the
  App (covers steps that happen *before* this code matters; useful for
  forks/SaaS migration), and end-user guide with screenshots of the
  modal flow.
- README mention.
- Manual QA pass against the registered App.

### Phase 8 — PR + handoff

- Branch: `feat/github-app-device-flow` (per CLAUDE.md naming).
- Commits: `feat(github-app): ...`.
- PR description includes the manual test plan inline (CI can't run
  it).
- Add the `IMPL-0010` link in the PR body.
- **Do not merge.** `@galanko` reviews + merges per CLAUDE.md.

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| User has Cliff on a non-default port; `setup_url` redirect lands on the wrong host | Medium | Manual `installation_id` paste fallback in modal. Documented in setup guide. |
| GitHub introduces forced token expiry on user access tokens | Low (V1) / Higher (later) | Refresh path is implemented from day one even if disabled by default; flipping a setting on the App enables it without code changes here. |
| Process restart drops in-flight polling task | Low impact | 15-minute window only; user clicks "Try again". Documented. |
| Concurrent `/connect` calls double-issue device codes | Low | Idempotency check in `/connect` returns existing in-flight row. Test covers this. |
| MCP server starts before refresh completes after a 401 | Low | The refresh hook lives in our `github_client.py` (used for posture probes). The MCP-server-spawned-by-OpenCode path doesn't refresh — V1 acceptable; documented. |
| PAT user upgrades to App, App fails for them, no rollback path | Low | We **don't delete** the PAT credential or row on archive. User clicks "Re-enable PAT" (existing PAT card stays in the UI as archived; existing CRUD already supports re-enable). |
| `client_secret`-required revocation forgotten by user | Medium | Disconnect toast surfaces the manual revoke URL prominently. SaaS milestone closes this gap. |

## Out of scope (for this plan)

- Webhook handling.
- GHES-specific endpoints.
- Lifting App scopes to write (separate ADR + UX work for action-tier
  upgrades).
- Multiple simultaneous GitHub installs on one instance.
- Replacing the GitHub MCP server's auth (still env-var bearer).

## Open items requiring CEO input

1. Confirm that the App's `setup_url` should be hard-coded to
   `http://localhost:8000/api/integrations/github/setup` for V1 — or
   whether we should also document a parameterized variant for
   staging/SaaS now.
2. Confirm App's user-token-expiry setting: **disabled** for V1
   (recommended) vs. **enabled** (forces refresh path to be
   exercised in production from day one).
3. Confirm we ship `CLIFF_GITHUB_APP_CLIENT_ID` and
   `CLIFF_GITHUB_APP_SLUG` as **defaulted** (App goes live) or
   **unset** (dark launch, flip via env). Recommendation: defaulted,
   since the App is intended to be the user-facing path going
   forward.
