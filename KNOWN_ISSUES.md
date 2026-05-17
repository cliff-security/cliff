# Known Issues

Tracked problems to fix in focused sessions. Remove items once resolved.

---

### Manual smoke — Solve flow after PRD-0006 Phase 1 ships

**Status:** Open — to be re-verified after the alpha cut lands.

**Why this is here:** PRD-0006 Phase 1 renames Findings → Issues on the
frontend (route + nav) and adds a pinned Review section with stage-aware
row actions. The IMPL plan (`docs/architecture/plans/IMPL-0006-issues-page-phase-1.md`)
explicitly preserves the existing `Solve` flow: clicking a Todo row should
still create a workspace and navigate to `/workspace/:id` — same
behaviour as today, just a different entry point.

**How to smoke this:**

1. `scripts/dev.sh`, open the app at http://localhost:5173.
2. Confirm the SideNav shows only **Dashboard** and **Issues** (Settings
   anchored bottom). No Findings, Workspace, or History entries.
3. Confirm `/findings` redirects to `/issues` (browser address bar).
4. Confirm `/findings/:id` redirects to `/issues/:id` for any existing
   finding ID.
5. Confirm `/workspace/:id` still resolves and renders the existing
   WorkspacePage when navigated to directly.
6. On the Issues page, click an existing **Todo** row → expect: workspace
   is created, browser navigates to `/workspace/<new-id>`, the existing
   workspace UI renders unchanged.
7. Pick an issue that already has a workspace and a plan (Review section,
   "Plan ready") → click the **Review plan** button → expect: navigate
   directly to `/workspace/<existing-id>`, no new workspace created.
8. Open and close the **In progress** section header → expect: collapse
   state persists on remount within the same browser session and the
   stage-breakdown caption reads `{n} planning · {n} generating ·
   {n} opening PR · {n} validating`.
9. Dismiss the migration banner → expect: hidden until a new tab is
   opened.

**If any step fails:** stop, capture the network log + DOM snapshot, and
re-open the IMPL-0006 plan before patching. Do not silently mutate
backend behaviour.

---

### SSE stream uses global event bus — no per-session filtering at source

**Impact:** The OpenCode `/event` endpoint is a global stream. Our backend filters by `sessionID`, but still receives all events for all sessions. With many concurrent sessions this could become a bottleneck.

**Workaround:** None needed for single-user MVP. Revisit if performance degrades.

**Fix idea:** Check if OpenCode supports per-session event subscriptions. If not, add server-side event routing in the backend.

---

### Old sessions accumulate in OpenCode with no cleanup

**Impact:** Every "New Session" click creates a permanent session in OpenCode. There's no cleanup, expiry, or delete mechanism in our app.

**Workaround:** Restart OpenCode to clear sessions.

**Fix idea:** Add session delete API. Add session age/limit management.

---

### Frontend SSE connection doesn't auto-reconnect after backend restart

**Impact:** If the backend restarts while the frontend is open, the SSE stream dies silently. The user must refresh the page.

**Workaround:** Refresh the browser after restarting the backend.

**Fix idea:** Add reconnection logic in the EventSource handler with a status indicator.

---

### Chat history lost on page refresh

**Impact:** Messages are only in React state. Refreshing the page loses the conversation. The session still exists in OpenCode but we don't reload its messages.

**Workaround:** Don't refresh while chatting.

**Fix idea:** On session load, fetch message history from OpenCode's `GET /session/{id}` and populate the chat.

---

### Send button stays disabled after an error

**Impact:** If a message send fails or the model returns an error, the `sending` state may not reset properly, leaving the input disabled.

**Workaround:** Click "New Session" to reset.

**Fix idea:** Ensure all error paths in the SSE handler reset the `sending` state.

---

### opencode.json model must use provider-qualified ID

**Impact:** The model in `opencode.json` must be the full `provider/model-id` format (e.g., `openai/gpt-4.1-nano`). Short names like `gpt-4.1-nano` won't work. This is an OpenCode requirement but not obvious.

**Workaround:** Always use the full qualified model ID.

**Fix idea:** Document this clearly. Validate the model format in our config loader. Future Settings page should show a dropdown of available models.

---

### opencode.json can drift from runtime config

**Impact:** Model changes made via the Settings UI update OpenCode at runtime via `PUT /config`, but `opencode.json` must also be updated separately. If the write to the file fails silently, the next OpenCode restart will revert to the old model.

**Workaround:** ConfigManager writes to both the API and the file, but check `opencode.json` if the model reverts after a restart.

**Fix idea:** Add a startup check that compares `opencode.json` with the model stored in `app_setting` and reconciles if they differ.

---

### API keys set via Settings are lost on OpenCode restart

**Impact:** Keys set via `PUT /auth/{id}` only live in the OpenCode process memory. If OpenCode restarts (crash, deploy, manual restart), all keys are forgotten until our backend re-injects them.

**Workaround:** Keys are persisted in the `app_setting` table and re-injected on startup via `restore_keys_to_engine()`. If keys stop working after a crash, restart the backend.

**Fix idea:** Add a health-check hook that detects when OpenCode has restarted and automatically re-injects stored keys.

---

### Provider catalog may overwhelm the Settings UI

**Impact:** OpenCode supports 75+ providers. Showing all of them in the model selector or API key list can be noisy and hard to navigate.

**Workaround:** The UI shows providers with valid auth first, then a "show all" toggle for the rest.

**Fix idea:** Add a "favorites" or "pinned providers" feature so users can curate which providers appear by default.

---

## EXEC-0002 · Session D onboarding wizard (PR #58)

Tracked here so nothing in the deferred list gets lost. Session G is the planned landing site for most of these, but they are captured here in case Session G slips or scope changes.

### `OnboardingRepoResponse.verified` is frontend-only today

**Impact:** `ConnectionResultCard` (UX frame 1.3) renders `visibility`, `default_branch`, and `permissions` from a `verified` subobject that exists only in the MSW stub. The frozen Session-0 contract returns just `{ assessment_id, repo_url }`. When Session G flips to the real backend the verified card won't render during the 1.2 s auto-advance — the user sees the spinner row with no summary.

**Workaround:** None in prod today (MSW masks it).

**Fix idea:** Either (a) extend `OnboardingRepoResponse` on the backend with a `verified: VerifiedRepoSummary` subobject populated from the GitHub API response (preferred — two fields we already have), or (b) derive `repo_name` from `repo_url` in the component and gracefully omit the other fields. Captured as Session G step 2 in `docs/architecture/plans/EXEC-0002-session-prompts.md`.

---

### `ConnectionResultCard.permissions` assumes `string[]`

**Impact:** `verified.permissions.join(', ')` silently renders `[object Object]` if the backend ever returns object-shaped permissions (e.g. `{scope, granted}`). The frozen contract has no runtime guard.

**Workaround:** Typed as `permissions: string[]` in `api/onboarding.ts` — matches the MSW stub.

**Fix idea:** Lock the shape in the OpenAPI spec when Session G closes the contract gap above. Add a zod/typia validator at the fetch boundary if the shape becomes externally provided.

---

### No route guard on `/onboarding/*` for completed users

**Impact:** A user who finished onboarding can still bookmark or type `/onboarding/welcome` and re-enter the wizard over their active app. Nothing breaks, but it's a confusing state — and if they click Start Assessment again they'll trigger a second `POST /api/onboarding/complete`.

**Workaround:** None — Session 0 ships with `onboarding_completed` persisted but no guard reads it yet.

**Fix idea:** Gate the `/onboarding/*` routes behind a `GET /api/settings/onboarding-status` fetch and redirect to `/` when `onboarding_completed === true`. Belongs with Session G's feature-flag wiring (`CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED`).

---

### AI key entered in ConfigureAI is never persisted

**Impact:** The "Configure your AI model" step captures an API key in React state and drops it on navigation. The reassurance copy ("Keys stay on this machine · Cliff stores them in its local vault") is aspirational — the vault POST doesn't exist in Session D. `TODO(session-g)` is marked in `ConfigureAI.tsx::handleContinue`.

**Workaround:** Users can set keys via the existing Settings page after onboarding completes.

**Fix idea:** Session G wires `POST /api/settings/api-keys/:provider` from `handleContinue`, with a spinner + "Testing key…" state so the copy becomes truthful. Optionally add a real API validation call before advancing.

---

### Welcome page has no Back/exit affordance

**Impact:** A user who lands on `/onboarding/welcome` from a deep link has no way out except the URL bar — there's no top nav because the wizard renders outside `AppLayout`. Acceptable for v1.1 (the flag + future route guard make it unreachable for completed users), but worth fixing if a user ever needs to "skip for now."

**Workaround:** Type `/` or `/findings` into the URL.

**Fix idea:** Add a small "Skip setup" text link in `OnboardingShell` that routes to `/findings` and persists an `onboarding_skipped` marker, OR a top-right "Exit" affordance on Welcome only.

---

### MSW scaffolding ships in the repo until Session G

**Impact:** `frontend/src/test/msw/{browser,server,onboardingHandlers}.ts`, `frontend/public/mockServiceWorker.js`, and `startMockApi()` in `main.tsx` are all in the dev bundle. Tree-shaken from prod via `import.meta.env.DEV`, so no prod-size cost — but a contributor running `npm run dev` hits mocks by default instead of the real backend unless they set `VITE_USE_REAL_API=1`.

**Workaround:** `VITE_USE_REAL_API=1 npm run dev` to bypass MSW in dev.

**Fix idea:** Session G step 1 removes `startMockApi()`, `browser.ts`, and `mockServiceWorker.js`. The Vitest `server.ts` stays.

---

### Frontend bundle crosses 500 kB warn threshold (808 kB / 238 kB gzip)

**Impact:** Vite prints the "chunks larger than 500 kB" warning on every build. Current main-chunk is 808 kB raw / 238 kB gzip. Session D added ~15 kB gzip (MSW worker, onboarding pages, TokenHowToDialog) — not the main offender, but also not helping.

**Workaround:** None; first-paint is still fine.

**Fix idea:** Route-level code splitting via `React.lazy` on the less-hot pages (`HistoryPage`, `SettingsPage`, `WorkspacePage`). Session F will add `html-to-image` (~80 KB gzipped) behind a dynamic import; follow the same pattern for the workspace sidebar. Track bundle size in CI via `size-limit` or similar if the number keeps growing.

---

### Orphan PR after executor mid-stream crash/timeout (EF-B14 residual)

**Status:** Open — agent-layer fix tracked, not user-facing for now.

**Why this is here:** PR #163 reconciles `Finding.pr_url` from `AgentRun.structured_output` on close, which fixes the common drift case (executor completed, recorded `pr_url`, but the column was never written). It does NOT recover the rare case where the `remediation_executor` agent dies mid-stream (timeout, OpenCode crash, host pause) AFTER `gh pr create` succeeded on GitHub but BEFORE the agent emitted parseable structured output. In that path the AgentRun row is `status='failed'`, `structured_output=null`, sidebar untouched — the DB has no record that a PR was opened, even though one exists on GitHub. The QA-0001 fsevents incident (Q01 §B14, PR #6 on cliff-security/NodeGoat) sits exactly here.

**Why not policy-fix it:** Blocking close with a 4XX would punish users for an agent reliability failure they can't act on from the UI. The fix belongs in the agent layer.

**Detection today:** When close happens against a workspace with executor runs but no recoverable `pr_url`, `mark_resolved_on_workspace_close` emits a `WARNING` log (`EF-B14: finding=… workspace=… — executor ran N time(s) but pr_url could not be reconciled …`). That's our only signal until the agent layer ships a real fix.

**Fix ideas (agent-layer):**
1. Executor writes intermediate state every N seconds (branch_name as soon as it's pushed, pr_url as soon as `gh pr create` returns) instead of only at terminal parse. A crash mid-stream then still leaves enough breadcrumbs to reconcile.
2. On workspace open, post-mortem detect orphan branches by listing `gh pr list --head cliff/fix/<finding-slug>` and patching `Finding.pr_url` if a match exists.
3. Executor checkpoint: write `RepoAgentStatus` to disk after each major tool call so a crash after `git push` but before `gh pr create` is recoverable on retry.

**Workaround for affected users:** Click the link or `gh pr list` on the target repo; PATCH the finding directly: `curl -X PATCH /api/findings/<id> -d '{"pr_url":"https://…"}'`. (Not great — that's why we're not making the close handler force this.)
