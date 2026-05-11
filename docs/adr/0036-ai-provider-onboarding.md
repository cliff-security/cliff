# ADR-0036: Tiered AI provider onboarding

**Date:** 2026-05-11
**Status:** Proposed
**Related:**
- ADR-0011 (Serene Sentinel design system)
- ADR-0012 (Runtime settings via OpenCode API) — partially superseded for AI keys
- ADR-0014 (Workspace runtime architecture) — env-var injection seam
- ADR-0016 (Credential vault — AES-256-GCM)
- ADR-0035 (GitHub App + Device Flow onboarding) — encryption precedent

## Context

OpenSec ships today with a single-tier "paste your API key" AI configuration. The user picks a provider card (OpenAI / Anthropic / Gemini / Other), pastes a key, and clicks `Test and continue` (see `frontend/src/pages/onboarding/ConfigureAI.tsx`). On success the key is persisted by `ConfigManager.set_api_key()`, which writes it to the `app_setting` table and pushes it to the singleton OpenCode process via `PUT /auth/{id}` (`backend/opensec/engine/config_manager.py:81`).

This works for users who already hold an Anthropic, OpenAI, or OpenRouter key — a small slice of the target audience. For everyone else, the onboarding cliff is steep: sign up for a provider, fund an account, generate a key, paste it. The current state is the principal drop-off between "downloaded OpenSec" and "ran their first assessment."

The recently merged GitHub App + Device Flow work (ADR-0035, PR #145) reshaped GitHub onboarding into a "two-click install" experience. The AI provider onboarding needs to feel like its peer — same calm, same number of decisions, same time-to-first-value.

OpenCode's own limitations constrain the implementation:
- No native OAuth support (anomalyco/opencode#7766).
- `/connect` command is unreliable (anomalyco/opencode#15381 — config doesn't always persist, surfaces as "No endpoints found").
- `auth.json` storage triggers cryptic cookie-auth failures (anomalyco/opencode#12436).
- The documented reliable path is **env-var substitution in `opencode.json` via `{env:VAR_NAME}`**.

The workspace runtime (ADR-0014) already exposes the right seam: `WorkspaceProcessPool.start(env_vars=...)` injects env into the per-workspace subprocess at spawn time (`backend/opensec/engine/pool.py:142`). Today it's used for `GH_TOKEN`. We ride the same channel for AI keys.

## Decision

Replace the single-tier paste flow with a **three-tier onboarding** that fires in priority order — auto-detect, then OpenRouter OAuth, then direct BYOK — and inject the resulting key into OpenCode subprocesses via environment variables.

### Tier model

| Tier | Path | Clicks | Audience |
|------|------|--------|----------|
| 1 | Auto-detect existing key (Claude Code, env vars, Aider, OpenAI config) | 1 | Users who already use AI tools |
| 2 | OpenRouter OAuth (PKCE) — backend runs the dance, returns a static key | 2 | New-to-AI users |
| 3 | Direct BYOK (Anthropic / OpenAI / custom) with deep-linked instructions | 3–4 | Users who insist on a specific provider |

The tiers are presented in sequence, not as a three-way choice. Auto-detect runs silently on first boot. If it succeeds, a non-intrusive banner offers one-click adoption. If it fails (or the user declines), the AI provider modal opens with **one primary CTA** ("Connect with OpenRouter") and **one secondary link** ("I have my own API key").

### Model defaults — Sonnet 4.6 everywhere it fits

The model is hidden in the UI across all tiers. OpenSec picks:

| Provider | Default model | Notes |
|----------|---------------|-------|
| OpenRouter | `anthropic/claude-sonnet-4-6` | First-class path. |
| Anthropic direct | `claude-sonnet-4-6` | First-class path. |
| OpenAI direct | `gpt-5` | Sonnet not available on OpenAI; UI surfaces a one-line "OpenSec is optimized for Claude — Claude tends to perform better on security reasoning. GPT-5 should still work." note at BYOK time and at first agent run. |
| Custom (OpenAI-compatible) | Required field on the BYOK form | User specifies; same "optimized for Claude" note. |

OpenSec is **opinionated about Claude Sonnet 4.6** for the security-reasoning workload. Defaults reflect that.

### Model override — env-var escape hatch, no UI in V1

There is no `Advanced → override` UI in V1. The override path is an env var per provider:

- `OPENSEC_AI_MODEL_OVERRIDE_OPENROUTER`
- `OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC`
- `OPENSEC_AI_MODEL_OVERRIDE_OPENAI`
- `OPENSEC_AI_MODEL_OVERRIDE_CUSTOM`

When any override is set:
- At app boot, a `WARNING` log line: `AI model override active for <provider>: <model>. OpenSec is tuned for claude-sonnet-4-6; performance may vary.`
- The override is surfaced on the Settings → AI provider card with a subtle warning chip ("Custom model: <name>. Default recommended.") so the override isn't invisible.

This satisfies the "override with a warning" requirement without adding a UI affordance that pushes model selection back into the primary flow.

### OAuth implementation

OpenRouter's PKCE flow exchanges a public `code_challenge` + private `code_verifier` for a static API key. We run the dance entirely in OpenSec's Python backend:
1. Backend mints PKCE pair + CSRF state, stores them in-memory keyed by `session_id`, TTL 10 minutes.
2. Backend starts a one-shot HTTP listener on `localhost:3000` (OpenRouter requires `:3000` for local callbacks — non-negotiable). Listener auto-shuts on callback or 5-minute timeout.
3. Frontend opens `https://openrouter.ai/auth?...` in a new tab.
4. OpenRouter redirects to `http://localhost:3000/callback?code=...&state=...`.
5. Backend validates state, exchanges code at `POST https://openrouter.ai/api/v1/auth/keys`, receives an API key, encrypts and persists it.
6. Frontend (polling every 1s) sees `status: connected` and updates the UI.

OpenCode is unaware OAuth happened — it only ever sees `OPENROUTER_API_KEY` in its environment.

### Storage and encryption — reuse `CredentialVault` (ADR-0016)

Persist AI integrations in a new `ai_integration` table — one row at a time (single-user, community edition):

```
id              TEXT PRIMARY KEY
provider        TEXT NOT NULL   -- openrouter | anthropic | openai | custom
api_key_ref     TEXT NOT NULL   -- foreign key into credential table (vault row id)
source          TEXT NOT NULL   -- autodetect | openrouter-oauth | byok
metadata_json   TEXT            -- e.g. OpenRouter user email, autodetect source path, base_url for custom
connected_at    TIMESTAMP NOT NULL
last_validated_at TIMESTAMP
```

The key itself is **not** stored on `ai_integration` directly. It is stored encrypted in the existing `credential` table via `CredentialVault.store()` (AES-256-GCM, `OPENSEC_CREDENTIAL_KEY` via keyring/env/file). `ai_integration.api_key_ref` points to that row.

This matches the merged GitHub App work (ADR-0035 / IMPL-0010) which also reuses `CredentialVault` for token storage. One encryption stack, one key resolver, one set of operational concerns.

### OpenCode subprocess wiring

The `opencode.json` template rendered into each workspace directory references the active model — never the key:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "<rendered at workspace-creation time>"
}
```

The key is **never written into config** — it lives only in the subprocess environment.

`WorkspaceProcessPool.start()` already accepts `env_vars`. The pool's caller reads the active `ai_integration`, resolves the key via `CredentialVault.retrieve()`, and passes `{"OPENROUTER_API_KEY": ...}` (or the provider's equivalent) into `pool.start(env_vars=...)`.

The singleton OpenCode process (port 4096, used by `/api/settings/providers/test` and the provider catalog endpoints) is **restarted** on AI-integration save/change/disconnect so its environment picks up the new key. Restart cost is ~1-2 seconds. The frontend status endpoint absorbs the blip.

### Migration

The existing paste-flow code (`ConfigManager.set_api_key()`, `POST /api/settings/api-keys/{provider}`, `ConfigureAI` page) stays alive in V1. Existing users keep working. A one-time banner offers the new flow:

> Try our new one-click AI setup.

The banner auto-hides after 30 days even if not dismissed, so users who like the old flow aren't nagged forever.

Until they accept, their key continues to flow through the OpenCode `/auth/keys` channel (which uses `auth.json` internally — a known anti-goal, but tolerable for already-onboarded users; switching them costs nothing once they adopt). New installs see only the new modal.

A follow-up ADR (post-v0.1-alpha) will retire the paste flow entirely.

### Audit logging

`POST /api/integrations/ai/autodetect/adopt`, `/byok`, `/openrouter/start`, `/openrouter/status` (terminal transitions only), and `/disconnect` emit audit events through the existing `AuditEvent` channel. The audit row records:
- Event type (`ai_integration.adopt` / `connect` / `disconnect`).
- Provider name.
- For adopt: the source path (`"ANTHROPIC_API_KEY env"`, `"~/.claude/.credentials.json"`) for forensic visibility — the audit log is local-only, so this is not a leak.
- Never the key value.

## Rejected alternatives

### Keep the single paste flow
Works for the technical sliver of users we already capture. Does nothing for the audience this work targets.

### OpenRouter OAuth as the only path
Strictly worse for users with an existing Anthropic or OpenAI account — forces them to create a second account on a service they don't need, with a markup on top of their existing relationship. Auto-detect + BYOK closes that gap.

### OAuth with Anthropic directly
Anthropic banned OAuth for third-party apps in February 2026. Not available to us.

### Bundled credits / shared API key
Three failure modes, any one disqualifying: abuse risk (one leaked key compromises every install), cost (free-tier credits at OpenSec's expense at unbounded scale), audit risk (we'd be a proxy for AI usage attributable to us, which violates the self-hosted positioning).

### Local LLM (Ollama) as the default
Local models are not yet competent at the security-reasoning tasks OpenSec leans on. Shipping with Ollama as the default would degrade the first-run experience for everyone. Park for v0.2+ as an optional Tier 4.

### Fernet + new `OPENSEC_SECRETS_KEY` (per brief)
The brief proposed a parallel Fernet-based encryption stack. We use `CredentialVault` (AES-256-GCM, ADR-0016) instead — same choice the merged GitHub App work made. One encryption stack across the codebase.

### A UI "Advanced → override" affordance for model selection
Pushes model choice back into the primary flow we're trying to remove it from. Env-var override + Settings-card warning chip achieves "configurable when needed, invisible by default."

### Putting the OAuth listener on the FastAPI port (8000)
OpenRouter requires `localhost:3000` for local callbacks. Not negotiable. Separate one-shot listener for the duration of the handshake.

### Persisting OAuth session state in DB
Sessions live 5 minutes and are tied to a running listener. A restart kills the listener regardless. In-memory dict with TTL is simpler and equivalent.

### Polling via SSE instead of HTTP polling
Polling at 1s for 5 minutes is 300 requests of trivial size. SSE adds a long-lived connection, complicates listener teardown, and gains nothing. Stick with polling.

## Consequences

### Positive
- New users go from `unconfigured → connected` in two clicks via OpenRouter, with no provider account creation up front (OpenRouter accepts Google / GitHub one-click sign-in).
- Existing-key users (Claude Code, Aider, env vars) reach `connected` in one click via auto-detect.
- Anthropic-direct users keep a fast path (~10 seconds) behind a secondary link.
- Model selection is hidden from the primary flow — Sonnet 4.6 is the opinionated default everywhere it fits.
- Keys never touch logs, never live in `opencode.json` or `auth.json`. Encrypted at rest via the existing audited vault.
- The workspace runtime's env-var injection (ADR-0014) absorbs all three tiers without changes — they all converge on a string in `os.environ`.
- Adopt-from-auto-detect actions are audit-logged with their source paths, so paranoid users (and ourselves) can audit "where did this key come from."

### Negative
- **Port 3000 is a hard external constraint.** Conflicts (other Node dev servers, Grafana dev rigs) require a clear fallback path to BYOK. We can't move the port without OpenRouter's cooperation.
- **No revocation on self-hosted disconnect.** Revoking an OpenRouter key requires their `client_secret`, which we cannot ship in self-hosted code. Disconnect clears our local copy and surfaces a copy-pasteable link to `openrouter.ai/settings/keys` for full revocation. Documented to the user.
- **Three tiers > one tier of complexity.** More UI states, more error paths. Mitigated by a strict state machine (TS discriminated unions on the frontend, explicit status enum on the backend).
- **Singleton OpenCode restarts on key change.** A ~1-2s blip every time the user saves a key. Provider-test will see one transient `connection refused` if it runs during the restart window; the UI absorbs this with a retry.
- **The paste flow lives on through migration.** Two code paths for AI keys until v0.2. Contained behind a 30-day banner; old code is removed in a follow-up ADR.
- **Auto-detect reads filesystem locations users didn't explicitly grant.** We scan `~/.claude/.credentials.json`, `~/.aider/.env`, `~/.config/openai/`, and four env vars on every Integrations-page visit. The scan is read-only and never writes to OpenSec storage without an explicit click. Setup guide enumerates every path.
- **OpenAI-direct users see a "tuned for Claude" warning** at BYOK time and at first agent run. Some users may read this as us steering them toward a competitor. Mitigated by framing it as performance guidance, not policy.

### Neutral
- The existing `app_setting` table keeps its `api_key:*` rows for backwards compatibility. They're authoritative until a user adopts the new flow; after adoption the new `ai_integration` row wins.
- `ConfigureAI.tsx` (the wizard step) stays but switches its primary CTA to the new flow on fresh installs. Existing users continue through it unchanged.

## References

- OpenCode env-var substitution docs: https://opencode.ai/docs/config — `{env:VAR_NAME}` reference
- OpenCode native OAuth tracking issue: https://github.com/anomalyco/opencode/issues/7766
- OpenCode `/connect` persistence bug: https://github.com/anomalyco/opencode/issues/15381
- OpenCode `auth.json` cookie-auth failures: https://github.com/anomalyco/opencode/issues/12436
- OpenRouter OAuth PKCE: https://openrouter.ai/docs/use-cases/oauth-pkce
- ADR-0014 (workspace runtime, env-var injection seam)
- ADR-0016 (credential vault, encryption-at-rest pattern)
- ADR-0035 (GitHub App + Device Flow — encryption precedent)
- IMPL-0011 (this work's implementation plan)
