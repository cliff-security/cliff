# IMPL-0011: Tiered AI provider onboarding

**ADR:** [docs/adr/0036-ai-provider-onboarding.md](../../adr/0036-ai-provider-onboarding.md)
**Brief:** `CLAUDE-CODE-PROMPT-ai-provider.md`
**Status:** Draft
**Date:** 2026-05-11
**Branch:** `feat/ai-provider-onboarding`
**Commit prefix:** `feat(ai-provider):`

## Summary

Replace the single-tier "paste an API key" AI configuration with a tiered onboarding (auto-detect → OpenRouter OAuth → direct BYOK). The model is hidden in the UI across all three tiers; OpenSec opinionates on Sonnet 4.6 (`anthropic/claude-sonnet-4-6` on OpenRouter, `claude-sonnet-4-6` direct) and falls back to `gpt-5` for OpenAI-direct with a "tuned for Claude" warning. Keys flow into per-workspace OpenCode subprocesses via the existing env-var injection seam (`WorkspaceProcessPool.start(env_vars=...)`); they never touch `opencode.json` or `auth.json`.

Encryption reuses `CredentialVault` (AES-256-GCM, ADR-0016) — same choice as the merged GitHub App work (ADR-0035, PR #145).

## Team assignments

| Layer | Team | Files |
|-------|------|-------|
| DB migration + repo | App Builder | `backend/opensec/db/migrations/0017_ai_integration.sql`, `backend/opensec/db/repo_ai_integration.py` |
| Encryption (reuse) | App Builder | `backend/opensec/integrations/vault.py` (no changes) |
| Auto-detect scanner | App Builder | `backend/opensec/ai/autodetect.py` |
| OAuth PKCE + listener | App Builder | `backend/opensec/ai/openrouter_oauth.py` |
| BYOK validators | App Builder | `backend/opensec/ai/validators.py` |
| AI integration service | App Builder | `backend/opensec/ai/service.py` |
| API routes | App Builder | `backend/opensec/api/routes/ai_integrations.py` |
| OpenCode env injection | Agent Orchestrator | `backend/opensec/engine/pool.py` callers, `backend/opensec/workspace/context_builder.py` |
| Workspace opencode.json template | Agent Orchestrator | wherever `opencode.json` is rendered into the workspace dir |
| Singleton restart on key change | Agent Orchestrator | `backend/opensec/engine/process.py`, `backend/opensec/main.py` lifespan |
| Modal + state machine | App Builder | `frontend/src/components/ai-provider/` |
| Auto-detect banner | App Builder | `frontend/src/components/ai-provider/AutoDetectBanner.tsx` (mount in `IssuesPage` / `DashboardPage`) |
| Settings status card | App Builder | `frontend/src/components/ai-provider/AIProviderStatus.tsx` |
| User docs | App Builder | `docs/guides/setup-ai-provider.md` |

Cross-vertical interface: the **AI integration service** in `backend/opensec/ai/service.py` is the single point that resolves a key and an env-var name for a given provider. Both the workspace pool and the singleton OpenCode launcher import from it. No frontend → agent coupling; no agent → integration coupling beyond this one read interface.

Migration number `0017` confirmed by inspecting `backend/opensec/db/migrations/` — `0016` is the GitHub App table from PR #145.

## Task breakdown (TDD-first)

### Phase A — Storage + service layer (App Builder)

Tests first in each task.

#### A1 — DB migration `0017_ai_integration.sql`
- New table per ADR-0036 (`id`, `provider`, `api_key_ref`, `source`, `metadata_json`, `connected_at`, `last_validated_at`).
- Foreign key `api_key_ref` → `credential.id` `ON DELETE RESTRICT`.
- Unique index on `(provider)` — community edition is single-row-per-provider, and we treat "active" as the most recently `connected_at`.
- Test: `tests/test_migration_0017.py` — schema matches expected, FK enforced, can insert + read.

#### A2 — Pydantic models
- `AIProvider` enum: `openrouter | anthropic | openai | custom`
- `AIIntegration` (read), `AIIntegrationCreate` (write).
- `AIStatus` for the status endpoint: `{ state: "unconfigured" | "connected", provider?, source?, connected_at?, metadata?, override_model? }`.
- Test: `tests/test_models_ai_integration.py` — validation, enum coercion, round-trip JSON.

#### A3 — Repo layer `repo_ai_integration.py`
- `create`, `get_active`, `delete`, `update_last_validated`.
- One row at a time — `create` overwrites prior active row by deleting it first (single-user).
- Test: `tests/test_repo_ai_integration.py` — CRUD round-trip; cascade behavior verified.

#### A4 — Provider catalog (constant)
- `backend/opensec/ai/catalog.py` — for each `AIProvider`: `env_var_name`, `default_model`, `console_url`, `key_hint` (e.g. `"sk-ant-"`).
- `default_model` values per ADR-0036: openrouter → `anthropic/claude-sonnet-4-6`, anthropic → `claude-sonnet-4-6`, openai → `gpt-5`, custom → `None` (required field).
- `resolve_model(provider)` — reads the env-var override (`OPENSEC_AI_MODEL_OVERRIDE_<PROVIDER>`) if set, else returns `default_model`. Logs a `WARNING` once at startup if any override is active.
- Tests: `tests/test_ai_catalog.py` — every `AIProvider` enum value has an entry; env-var override returns the override; warning is logged once and only once.

#### A5 — `AIIntegrationService`
- `get_active() -> AIIntegration | None`
- `adopt_detected(provider, raw_key, source_path) -> AIIntegration` (validates, encrypts via vault, persists, audit-logs the source path)
- `save_byok(provider, raw_key, base_url=None) -> AIIntegration`
- `complete_oauth(provider, raw_key, metadata) -> AIIntegration`
- `disconnect() -> None`
- `resolve_env_for_workspace() -> dict[str, str]` — returns e.g. `{"OPENROUTER_API_KEY": "..."}` or `{}` if unconfigured. **This is the cross-vertical interface.**
- All key strings stay within the service boundary — callers receive env-var dicts, never raw keys.
- Test: `tests/test_ai_integration_service.py` — covers each method including the encryption round-trip, the env-var-name selection, the audit-log emission.

### Phase B — Auto-detect (App Builder)

#### B1 — Scanner `backend/opensec/ai/autodetect.py`
Priority order, first match wins, returns `DetectedKey(provider, source, raw_key)` or `None`:
1. `~/.claude/.credentials.json` — JSON; look for top-level `anthropic_api_key` or nested under `accounts[].api_key`. Tolerate malformed files (return `None`, never raise).
2. `ANTHROPIC_API_KEY` env var.
3. `OPENROUTER_API_KEY` env var.
4. `OPENAI_API_KEY` env var.
5. `~/.aider/.env` — parse for `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`.
6. `~/.config/openai/` — look for an `auth.json` or `config` containing a key.

- The scanner reads but never writes. Empty/malformed source → skip and continue.
- Returns the raw key string only at the boundary that owns the adoption decision; everywhere else it returns a "found yes/no + provider + source" sentinel so the key doesn't sprawl.
- Test: `tests/test_ai_autodetect.py` — covers each source, malformed file tolerance, priority order, missing-file resilience. Uses `tmp_path` + monkeypatch on `os.environ` and `Path.home()`.

#### B2 — Adopt endpoint flow
- `GET /api/integrations/ai/autodetect` → returns `{ found: bool, provider?, source? }` (never the key).
- `POST /api/integrations/ai/autodetect/adopt` → re-runs the scan, validates the detected key against the provider, encrypts and persists, emits an audit event with the source path. Returns the new `AIStatus`.
- Test: `tests/test_routes_ai_autodetect.py` — both endpoints, including the case where the user clicks adopt but the env has changed underneath; verify the audit event records the source path.

### Phase C — OpenRouter OAuth (App Builder)

#### C1 — PKCE primitives `backend/opensec/ai/openrouter_oauth.py`
- `generate_pkce_pair()` → `(code_verifier: str, code_challenge: str)`; verifier is 43-char URL-safe random, challenge is `base64url(sha256(verifier))` without padding.
- `generate_state()` → 32-char URL-safe random CSRF token.
- Test: `tests/test_pkce.py` — pair determinism (challenge derives from verifier), length contracts, alphabet.

#### C2 — Session store
- In-memory dict `{session_id: OAuthSession}`. `OAuthSession` carries `verifier`, `state`, `created_at`, `status`, `listener_task`, `result_key` (transient, cleared after consumption).
- TTL: 10 minutes for state, 5 minutes for the listener.
- Test: `tests/test_oauth_session_store.py` — TTL eviction, status transitions, double-callback rejection.

#### C3 — Port 3000 one-shot listener
- `asyncio.start_server` on `127.0.0.1:3000`.
- Parses a single GET `/callback?code=...&state=...` (manual HTTP — no aiohttp dependency needed for one request).
- On match: stores `code` on the session, sends a 200 with a small HTML "you can close this tab" page, then `server.close()`.
- On port-in-use (`OSError: [Errno 48]`): bubbles a typed `Port3000UnavailableError` so the start endpoint can return a 409 with the friendly fallback copy.
- Auto-cancels after 5 minutes.
- Test: `tests/test_oauth_listener.py` — happy path, port-in-use, timeout (uses real `asyncio.start_server` on `127.0.0.1:0` for an isolated test, then injects port 3000 mocking for the conflict case).

#### C4 — Code exchange
- `POST https://openrouter.ai/api/v1/auth/keys` with `{ code, code_verifier, code_challenge_method: "S256" }`.
- Receives `{ key, user_id?, user_email? }`. Persists via `AIIntegrationService.complete_oauth(...)`.
- Test: `tests/test_oauth_exchange.py` — happy path (mocked `httpx`), 4xx response, network error, malformed response body.

#### C5 — OAuth API routes
- `POST /api/integrations/ai/openrouter/start` → mints session, starts listener, returns `{ auth_url, session_id }`. On port conflict returns 409 `{ error: "port_3000_in_use" }`.
- `GET /api/integrations/ai/openrouter/status?session_id=X` → `{ status: "waiting" | "connected" | "denied" | "error" | "timeout", detail? }`. **Returns 404 for unknown session_id** so accidental enumeration is bounded.
- Test: `tests/test_routes_ai_openrouter.py` — start happy path, start with port conflict, full pending → connected transition, denied case, timeout case.

### Phase D — Direct BYOK validators (App Builder)

#### D1 — Per-provider validators `backend/opensec/ai/validators.py`
- `validate_anthropic(key)` → `POST https://api.anthropic.com/v1/messages` with `model: claude-sonnet-4-6`, `max_tokens: 1`, body `[{role: "user", content: "ok"}]`. Headers: `x-api-key`, `anthropic-version: 2023-06-01`.
- `validate_openai(key)` → `POST https://api.openai.com/v1/chat/completions` with `model: gpt-5`, `max_tokens: 1`, body `[{role: "user", content: "ok"}]`. Header: `Authorization: Bearer <key>`.
- `validate_openrouter(key)` → `GET https://openrouter.ai/api/v1/key` with `Authorization: Bearer <key>`.
- `validate_custom(key, base_url, model)` → POST a `chat/completions` to the user's base URL.
- Returns typed `ValidationResult { ok: bool, error_code: "auth_failed" | "no_access" | "network" | "rate_limited" | "model_not_found" | None, error_message: str | None }`.
- Timeout: 5 seconds per probe.
- Test: `tests/test_byok_validators.py` — happy path, 401, 403, network error, timeout, malformed response. One test per provider.

#### D2 — BYOK API route
- `POST /api/integrations/ai/byok` body: `{ provider, api_key, base_url?, model? }`.
- Runs the validator first. If `ok`, persists via `AIIntegrationService.save_byok(...)`. Returns `AIStatus` or 400 with the validation error.
- Test: `tests/test_routes_ai_byok.py` — happy path per provider, all four error codes surface correctly.

### Phase E — Status + disconnect (App Builder)

#### E1 — Status endpoint
- `GET /api/integrations/ai/status` → `AIStatus`. Cached for 30s to avoid hot-pathing the vault on every page render.
- Includes `override_model: string | null` so the Settings card can render the warning chip.
- Test: `tests/test_routes_ai_status.py` — unconfigured, connected, override surfaced, cache invalidation on save.

#### E2 — Disconnect endpoint
- `POST /api/integrations/ai/disconnect` → deletes the `ai_integration` row and the linked `credential` row. Triggers a singleton restart (see F3). Emits an `ai_integration.disconnect` audit event.
- Returns 204.
- Test: `tests/test_routes_ai_disconnect.py` — happy path, idempotency (disconnect when already unconfigured returns 204), audit event emitted.

### Phase F — OpenCode integration (Agent Orchestrator)

#### F1 — Workspace `opencode.json` template
The workspace context builder writes an `opencode.json` per workspace dir. Update its renderer to:
- Set `model` to `catalog.resolve_model(active_provider)` (default per provider, or env-var override if set).
- Not reference any keys directly — keys flow only via env.
- If no provider is configured, write a template with the OpenRouter default and rely on env-var presence to fail loudly at LLM call time (the UI gates agent execution anyway).
- Test: `tests/test_workspace_opencode_config.py` — rendered file contains only the model + permission block, never raw keys; model matches provider; env-var override applies when set.

#### F2 — Workspace pool env injection
The pool's `start(env_vars=...)` already exists. The caller (workspace context builder or whichever module invokes `get_or_start`) must read `AIIntegrationService.resolve_env_for_workspace()` and merge it into the env-vars dict before calling `pool.start`.
- File: wherever `pool.get_or_start` is called for workspace spawns. Grep `pool.get_or_start` to find the call sites.
- Test: `tests/test_workspace_env_injection.py` — when an OpenRouter integration is active, the spawned process receives `OPENROUTER_API_KEY`; with no integration, no AI env var is set; with Anthropic active, `ANTHROPIC_API_KEY` only.

#### F3 — Singleton OpenCode restart on key change
- Add `restart_singleton()` to the engine process manager (or expose via an app-state hook).
- Call from `AIIntegrationService.adopt_detected` / `save_byok` / `complete_oauth` / `disconnect`.
- Restart spawns OpenCode with the new env (read from `service.resolve_env_for_workspace()`).
- Test: `tests/test_singleton_restart_on_key_change.py` — verify the singleton's env is updated; verify provider-test endpoint reflects the new provider within ~3s of save.

#### F4 — Log-leak prevention
- Audit every `log.info` / `log.debug` / `print` path that touches `api_key`, `verifier`, `code`, or `OAuthSession.result_key`.
- Add `__repr__` overrides on `AIIntegration`, `DetectedKey`, `OAuthSession`, `ValidationResult` to mask any key-shaped field.
- Test: `tests/test_ai_log_leak.py` — runs every endpoint with `caplog` and asserts the captured log text does not contain any of the test keys.

### Phase G — Frontend (App Builder)

#### G1 — Types and state machine
`frontend/src/components/ai-provider/types.ts`:
```ts
type AIProviderState =
  | { kind: "unconfigured" }
  | { kind: "detected-pending-adoption"; provider: Provider; source: string }
  | { kind: "picking-method" }
  | { kind: "openrouter-pending"; sessionId: string; startedAt: number }
  | { kind: "byok-form"; provider: Provider }
  | { kind: "validating" }
  | { kind: "connected"; provider: Provider; source: Source; metadata?: { email?: string }; overrideModel?: string }
  | { kind: "error"; reason: string; recoverable: boolean }
```
- TS discriminated union ensures every component handles every state.
- Test: `frontend/src/components/ai-provider/__tests__/stateMachine.test.ts` — transition table, every event from every state.

#### G2 — `useAIProviderStatus` hook (TanStack Query)
- Wraps `GET /api/integrations/ai/status`.
- Drives global "is AI configured" — used by every agent-action button to enable/disable + tooltip.
- Test: cached fetch, refetch on save.

#### G3 — `AIProviderModal.tsx`
- Root modal with state-machine routing.
- Mount in `AppLayout` so any agent trigger can open it.
- Closes on Esc / overlay click. **Dismissible** — closing returns to the app with AI buttons disabled (tooltip: "Configure AI provider first.").
- Serene Sentinel: tonal layering (L0 backdrop → L1 modal card → L2 inner panel), no 1px borders, ghost-border-only, Manrope head + Inter body, primary `#4d44e3` for CTAs, sentence case, Material Symbols icons.
- States routed to: `picking-method` → `OpenRouterConnectFlow` → `DirectBYOKForm` → success card.
- Test: snapshot + interaction tests for each routed sub-state.

#### G4 — `OpenRouterConnectFlow.tsx`
- Initial: primary CTA "Connect with OpenRouter."
- Loading: opens auth URL in new tab, switches to "Waiting for you to authorize on openrouter.ai" card + `[Open authorization page again]` link.
- Polling `/openrouter/status` every 1s, 5-min hard timeout (counts down visibly under the spinner).
- On `connected`: success card per brief copy ("Add $5 of credits..." with deep link + Start using OpenSec primary CTA).
- On `port_3000_in_use` (start returned 409): switches to friendly conflict card with `[Try again]` + `[Use my own API key]`.
- On `denied` / `timeout` / `error`: non-judgmental retry card.
- Test: each branch.

#### G5 — `DirectBYOKForm.tsx`
- Provider dropdown (Anthropic default, OpenAI, Other).
- Provider-specific instructions panel updates inline. Deep-link button (`[Open Anthropic console →]`) opens in a new tab — never auto-navigates the user away.
- When `openai` or `custom` is selected, a calm subtitle reads: "OpenSec is tuned for Claude. GPT-5 should still work but Claude tends to perform better on security reasoning." (Sentence case, no warning iconography — informational only.)
- Password-style key input.
- Live validation: debounced 250ms on blur / paste. Hits `POST /api/integrations/ai/byok` with the key. **Inline spinner** beside the field; **never** a blocking overlay. Inline ✓ on success, inline error copy on failure (401/403/network per brief).
- Save button disabled until validation passes.
- Cost callout under the field per brief.
- Test: per-provider validation, each error code surfaces correct copy, save disabled until validated, Claude-tuned note appears on OpenAI/custom only.

#### G6 — `AutoDetectBanner.tsx`
- Mounts on the route the user lands on after first boot (`/dashboard` and `/issues`).
- Calls `GET /api/integrations/ai/autodetect` on mount. If `found && !connected`, renders the banner.
- Dismissible (sessionStorage). Clicking `[Use it]` POSTs to `/adopt` and shows a toast confirmation. Clicking `[No, set up something else]` opens the modal at `picking-method`.
- Tonal banner — never red, never yellow. Background `surface-container` (L1).
- Test: shows when found, hides when dismissed, hides when connected.

#### G7 — `AIProviderStatus.tsx` (Settings page card)
- Shows current connection: "Connected via OpenRouter as user@example.com" (email pulled from metadata).
- If `override_model` is set, renders a subtle chip below the provider name: "Custom model: <name>. Default recommended."
- `[Disconnect]` and `[Switch provider]` actions.
- Disconnect dialog explicitly surfaces the "To fully revoke this key from OpenRouter's side, visit openrouter.ai/settings/keys" copy.
- Test: connected state per provider, override chip visible when set, disconnect confirmation flow.

#### G8 — Migration banner
- Shown to existing paste-flow users (detected via `GET /api/settings/api-keys` returning rows AND `GET /api/integrations/ai/status` returning `unconfigured`).
- "Try our new one-click AI setup."
- Auto-hides after 30 days (`first_shown_at` recorded in localStorage on first render).
- Dismissible (localStorage, immediate).
- Test: shows under correct conditions, hides after dismissal, hides after 30 days from first-shown.

#### G9 — Agent-button gating
- A small `useAIRequired()` hook returns `{ enabled: bool, tooltip: string, onClick: () => void }`.
- Every agent CTA (`Run agent`, `Enrich finding`, chat send, `Solve`) uses it: when `unconfigured`, the button is disabled with tooltip "Configure AI provider first." and clicking opens the modal at `picking-method`.
- For OpenAI/custom configured users on first agent click: a one-time toast "OpenSec is tuned for Claude; performance may vary with your selected model." (sessionStorage so it appears once per session).
- Test: button disabled in unconfigured state, opens modal on click, one-time toast appears for OpenAI users.

### Phase H — Documentation + final wiring

#### H1 — Setup guide
- `docs/guides/setup-ai-provider.md` — walks all three tiers with screenshots. Includes:
  - What auto-detect scans (so paranoid users know).
  - OpenRouter walkthrough (sign-in screen, authorize screen, success state).
  - BYOK walkthrough per provider (Anthropic, OpenAI).
  - The "tuned for Claude" guidance — why we recommend Claude, what to expect on other models.
  - Port 3000 conflict troubleshooting.
  - Disconnect + key-revocation instructions.
  - Model override env vars (`OPENSEC_AI_MODEL_OVERRIDE_*`) — documented as an advanced escape hatch with a "default recommended" callout.

#### H2 — Update ADR-0012 cross-reference
- ADR-0012 was "runtime settings via OpenCode API." Add a "Partially superseded by ADR-0036" note for the AI-key portion specifically (other config like model selection still flows through OpenCode `/config`).

#### H3 — Update CLAUDE.md
- Add a one-line bullet under "Key Domain Concepts" or "How It Runs" about AI provider env-var injection at workspace spawn.

## Test plan

### Backend unit tests (~25 new tests, target <2s total)
- `tests/test_migration_0017.py`
- `tests/test_models_ai_integration.py`
- `tests/test_repo_ai_integration.py`
- `tests/test_ai_catalog.py` (includes override env-var + warning-logged-once)
- `tests/test_ai_integration_service.py`
- `tests/test_ai_autodetect.py` (priority order, malformed files, missing-source resilience)
- `tests/test_pkce.py`
- `tests/test_oauth_session_store.py`
- `tests/test_oauth_listener.py` (happy path, port-in-use, timeout)
- `tests/test_oauth_exchange.py`
- `tests/test_byok_validators.py` (4 providers × happy + 4 error modes)
- `tests/test_routes_ai_autodetect.py` (includes audit event)
- `tests/test_routes_ai_openrouter.py`
- `tests/test_routes_ai_byok.py`
- `tests/test_routes_ai_status.py` (includes override surfaced)
- `tests/test_routes_ai_disconnect.py` (includes audit event)
- `tests/test_workspace_opencode_config.py`
- `tests/test_workspace_env_injection.py`
- `tests/test_singleton_restart_on_key_change.py`
- `tests/test_ai_log_leak.py` — runs every AI endpoint with `caplog`, asserts no key fragments in logs.

### Backend E2E tests
- `tests/e2e/test_ai_provider_e2e.py` — end-to-end mocked flow: `unconfigured → autodetect-found → adopt → connected → workspace spawns with env`. Skipped if OpenCode binary unavailable (follow existing E2E marker convention).

### Frontend tests (~15 new tests)
- State machine transition table.
- Each modal sub-component snapshot + interaction.
- `useAIProviderStatus` cache invalidation.
- `useAIRequired` gating behavior + one-time toast for OpenAI users.
- Auto-detect banner show/hide.
- Migration banner show/hide / 30-day auto-hide.
- Settings status card per provider, override chip rendering.

### Coverage gates for the PR
- Every endpoint has a test covering the happy path **and** the documented error states.
- Every state in the frontend state machine has a test that exercises at least one transition into and one transition out of it.
- `tests/test_ai_log_leak.py` is mandatory — keys never appear in stdout or stderr during any test.

## Manual QA checklist (for PR description)

Tests the parts CI can't fully simulate.

**Auto-detect (Tier 1)**
- [ ] With `ANTHROPIC_API_KEY` in the shell that launched OpenSec, opening `/dashboard` shows the auto-detect banner within 1s.
- [ ] Clicking `[Use it]` → toast + Settings shows "Connected via Anthropic (auto-detected from environment)".
- [ ] With `~/.claude/.credentials.json` present and **no** env vars, the banner says "Found a Claude Code API key" — not the env-var variant.
- [ ] Dismissing the banner sticks for the session; reloading does not bring it back.
- [ ] Adopt with an invalid key in the env → adopt endpoint returns the validator's error inline; banner stays open.
- [ ] After adopt, check `data/audit.log` (or query the audit route): a `ai_integration.adopt` event records the source path.

**OpenRouter OAuth (Tier 2)**
- [ ] Cold install + click "Connect with OpenRouter" → new tab opens to openrouter.ai/auth, modal shows the waiting card.
- [ ] Sign in via Google → authorize → tab shows "you can close this tab" → modal flips to success card within 2s.
- [ ] Success card primary CTA "Start using OpenSec" closes the modal; secondary "Add credits at openrouter.ai" opens in new tab.
- [ ] Pre-open another process bound to port 3000 (`python -m http.server 3000`) → click Connect → 409 returns friendly "another app is using port 3000" with `[Try again]` and `[Use my own API key]`.
- [ ] Start OAuth, don't authorize, wait 5 minutes → modal flips to timeout state with retry button.
- [ ] Start OAuth, click Deny on openrouter.ai → modal flips to non-judgmental retry card.
- [ ] Close the openrouter.ai tab without completing → can re-open from `[Open authorization page again]`.

**Direct BYOK (Tier 3)**
- [ ] "I have my own API key" link visible below primary CTA. Click → BYOK form.
- [ ] Anthropic selected by default. Provider-specific instructions visible. Deep-link button opens console.anthropic.com.
- [ ] Paste a valid Anthropic key → inline spinner within 250ms → ✓ within ~3s → Save enabled.
- [ ] Paste a malformed key → inline error matches brief copy ("This key was rejected by Anthropic. Check that it starts with `sk-ant-`...").
- [ ] Disconnect network → paste a key → inline "Can't reach Anthropic. Check your internet connection."
- [ ] Switch to OpenAI → "tuned for Claude" subtitle appears below the dropdown.
- [ ] Switch to OpenAI → instructions update inline → deep link goes to platform.openai.com.
- [ ] Switch to Other → base URL field appears alongside key field; both required; "tuned for Claude" subtitle appears.

**Model override**
- [ ] Launch OpenSec with `OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC=claude-opus-4-1` set. Backend logs a `WARNING` at boot mentioning the override.
- [ ] Settings → AI provider card renders the "Custom model: claude-opus-4-1. Default recommended." chip.
- [ ] Open a workspace → `opencode.json` contains `claude-opus-4-1`, not `claude-sonnet-4-6`.
- [ ] Unset the env var and restart → chip disappears, model returns to default.

**OpenCode integration**
- [ ] After connecting any provider, opening a workspace and running an agent succeeds.
- [ ] `ls data/workspaces/<id>/opencode.json` → file contains only model + permission blocks, **no raw key string** (grep the file for `sk-`, expect zero matches).
- [ ] `ps aux | grep opencode` → workspace OpenCode process env (inspect via `/proc/<pid>/environ` on Linux, `ps eww` on macOS) contains the expected `*_API_KEY`.
- [ ] After disconnect, running an agent surfaces the "Configure AI provider first" tooltip on the agent button.
- [ ] Switching providers (OpenRouter → Anthropic direct) — open a fresh workspace — the new process spawns with the new env var.

**Log leak prevention**
- [ ] Tail backend logs during a full BYOK save flow. Grep for the actual key string — expect zero matches.
- [ ] Tail logs during the OAuth flow. Grep for `code_verifier` and the returned key — expect zero matches.

**Migration**
- [ ] An existing paste-flow user (existing `api_key:anthropic` in `app_setting`) sees the one-time migration banner on `/dashboard`.
- [ ] Dismissing the migration banner persists across reloads.
- [ ] Set the localStorage `first_shown_at` to 31 days ago → reload → banner does not render.
- [ ] Opening the new modal and connecting via OpenRouter — old `app_setting` row remains untouched; the new `ai_integration` row is authoritative.

**Design system compliance (Serene Sentinel)**
- [ ] All button/link labels are sentence case ("Connect with OpenRouter", not "Connect With OpenRouter").
- [ ] Modal has no 1px solid borders; depth from tonal background shifts only.
- [ ] Modal CTA uses `#4d44e3` primary; text uses `on-surface` `#2b3437`, never pure black.
- [ ] Headlines use Manrope; body copy uses Inter.
- [ ] Icons are Material Symbols Outlined.

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Port 3000 conflict for users running dev rigs | Medium | Friendly 409 + BYOK fallback documented; surfaced in setup guide. |
| OpenRouter API contract change for code-exchange endpoint | Low | Mocked tests assert on response shape; manual QA after every OpenRouter changelog. |
| Singleton restart blip causes user-visible failures in provider-test | Low | Frontend retries the test once on `connection_refused`; backend returns a typed `engine_restarting` status. |
| Auto-detect scanner reads a file the user considered private | Medium | Scanner is read-only, never persists without an explicit click. Setup guide enumerates every path scanned. Adopt is audit-logged with source path. |
| Existing paste-flow users get into an inconsistent state when adopting the new flow | Medium | New `ai_integration` row wins authoritatively; old `app_setting` row left in place as fallback. Documented in ADR-0036. |
| `~/.claude/.credentials.json` format changes between Claude Code versions | Low | Parser tolerates missing fields; falls back to env-var detection. |
| Tests on a developer machine pollute the test by reading the real `~/.claude/.credentials.json` | Medium | All autodetect tests monkeypatch `Path.home()` to `tmp_path`. Enforced via a session-scoped fixture. |
| OpenAI-direct users feel steered to Claude by the "tuned for Claude" copy | Medium | Phrase as performance observation, not preference. "Should still work" — invitation, not warning. |

## Out of scope (explicitly)

- Ollama / local LLM (parked for v0.2+).
- Multi-account / multi-provider concurrent configurations (community edition is single-row).
- Server-side revocation of OpenRouter keys on disconnect (would require shipping `client_secret`).
- Removing the legacy paste flow (separate follow-up ADR post-v0.1-alpha).
- UI model selection in the primary flow (env-var override only).
- Telemetry / "how many users picked which tier" — opt-in analytics is a separate decision.

## CEO answers folded into this plan (2026-05-11)

1. ✅ Encryption: reuse `CredentialVault` (matches the merged GitHub App work, ADR-0035 / IMPL-0010).
2. ✅ Default model = Sonnet 4.6 across all providers where available (OpenRouter, Anthropic direct). OpenAI-direct defaults to `gpt-5` with a "tuned for Claude" note. Override via per-provider env vars + Settings warning chip; no UI affordance.
3. ✅ Audit-log the source path on adopt-from-autodetect.
4. ✅ Migration banner auto-hides after 30 days from first render.
5. ✅ "Advanced → override" UI dropped from V1 entirely.
