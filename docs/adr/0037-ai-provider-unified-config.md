# ADR-0037 — AI provider configuration is unified around one canonical state

* **Status**: Accepted
* **Date**: 2026-05-15
* **Supersedes the model-selection portion of**: ADR-0036 (env-var-only override)
* **Related**: ADR-0035 (tiered onboarding), ADR-0014 (workspace runtime), ADR-0016 (credential vault), IMPL-0011 (onboarding rollout)

## Context

The AI provider feature grew layer by layer — autodetect, OpenRouter OAuth,
BYOK, the readiness probe, and finally `CLIFF_AI_MODEL_OVERRIDE_*` env vars.
Each addition added a new place that answers "which model is in use," and
operators were hitting drift between them:

* `app_setting(key="model")` — the user's stored choice (CLI `cliff model set`,
  legacy ProviderSettings UI).
* `catalog.resolve_model(provider)` — catalog default, can be overridden by an
  `CLIFF_AI_MODEL_OVERRIDE_<PROVIDER>` env var. Surfaced through
  `AIStatus.model` to the new Settings card.
* `opencode_client.get_config()` — what the singleton OpenCode actually has
  loaded right now. Surfaced through `/health.model`.
* Per-workspace `opencode.json` — reconciled at spawn (Q01 B06b fix) so
  workspaces use the active provider's model. Could disagree with the
  singleton's `opencode.json` if the user changed providers without
  restarting Cliff.

The reported symptom on a running `:8001` instance:

> the UI shows me we are using Anthropic with Sonnet, but we are using
> Anthropic with Haiku

Two UIs (`AIProviderStatus` reading the env-override-aware status, and the
old `ProviderSettings` reading `/api/settings/model`) reading different
groups, with a third value (the per-workspace `opencode.json`) driving
the actual agent run. No way for a user to tell which one was real.

OpenCode supports many providers natively (Anthropic, OpenAI, Google,
OpenRouter, Ollama, OpenAI-compatible custom). Cliff exposed only four,
and gave no model picker — every change had to go through the CLI or an
env var. The same UI surface that fixes the drift problem is the right
place to add a picker.

## Decision

**One canonical state, two write boundaries, one read.**

### Canonical state

* **Provider + key + metadata** → `ai_integration` row + `credential` vault
  entry, owned by the same `integration_config` row (cascade on delete).
* **Active model** → `app_setting(key="model")`. ID format
  `<provider>/<model>` where the provider prefix MUST match the active
  `ai_integration.provider`.

Every other location (per-workspace `opencode.json`, the singleton
`opencode.json`, the in-process env cache) is **derived** and reconciled
from these two rows. The env-var override `CLIFF_AI_MODEL_OVERRIDE_*`
is preserved as a **dev/CI escape hatch**, no longer surfaced in the
picker. It does not override the canonical row at workspace-spawn time —
only the catalog-default fallback. (Operators who want a global override
should use the picker instead.)

### Two write boundaries

* **`AIIntegrationService.save_byok` / `complete_oauth` / `adopt_detected`**
  write the integration row + credential atomically AND set
  `app_setting(model)` in the same transaction. Caller-supplied model
  wins; existing stored model wins if its prefix matches the new provider;
  otherwise the catalog default. This eliminates the "switched provider,
  stored model still points at the old provider" footgun.
* **`AIIntegrationService.set_model`** changes the canonical model without
  re-saving the key. Rejects ids whose prefix doesn't match the active
  provider. Triggers the `on_key_change` hook so the singleton restarts
  and workspaces pick up the new model at next spawn.

### One read

`AIIntegrationService.get_status()` returns:

```python
AIStatus(
    state=...,
    provider=...,
    source=...,
    metadata=...,
    model=...,            # canonical from app_setting
    override_model=...,   # set only if CLIFF_AI_MODEL_OVERRIDE_* is active
    live_probe=LiveProbe(
        ok=...,
        opencode_model=..., # what OpenCode actually has loaded
    ),
)
```

If `live_probe.opencode_model != model`, the UI shows a drift banner with
a one-click `Reconcile` action that writes the canonical model again and
restarts the singleton. The CLI's `cliff status` surfaces the same drift
in its JSON output (`drifted: true`, `canonical_model`, `opencode_model`).

### Provider support

| Provider     | Env vars                  | Default model                   |
|--------------|---------------------------|---------------------------------|
| OpenRouter   | `OPENROUTER_API_KEY`      | `openrouter/tencent/hy3-preview`|
| Anthropic    | `ANTHROPIC_API_KEY`       | `anthropic/claude-haiku-4-5`    |
| OpenAI       | `OPENAI_API_KEY`          | `openai/gpt-5`                  |
| Google       | `GEMINI_API_KEY`          | `google/gemini-2.5-flash`       |
| Ollama       | `OLLAMA_BASE_URL`         | none — picker queries `/api/tags`|
| Custom       | `OPENAI_API_KEY` + base   | none — user supplies            |

Google and Ollama are **new** in this ADR. The implementation is thin:
OpenCode handles all the provider plumbing already; we add catalog
entries, validators, BYOK form tiles, and env injection.

### Architecture diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                        WRITE PATHS (3)                             │
│                                                                    │
│  Settings UI ─┐                                                    │
│  CLI ─────────┼──► AIIntegrationService                            │
│  Autodetect ──┘     - save_byok / complete_oauth / adopt_detected  │
│                     - set_model (picker)                           │
│                            │                                       │
│                            ▼                                       │
│                ┌──────────────────────────────┐                    │
│                │  CANONICAL STATE (atomic)    │                    │
│                │  - ai_integration row        │                    │
│                │  - credential vault entry    │                    │
│                │  - app_setting(model)        │                    │
│                └──────────────┬───────────────┘                    │
│                               │                                    │
│                               ▼                                    │
│                ┌──────────────────────────────┐                    │
│                │  on_key_change hook fires:   │                    │
│                │  - refresh env cache         │                    │
│                │  - refresh model cache       │                    │
│                │  - write singleton           │                    │
│                │    opencode.json             │                    │
│                │  - restart singleton OpenCode│                    │
│                └──────────────────────────────┘                    │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                         READ PATH (1)                              │
│                                                                    │
│  GET /api/integrations/ai/status                                   │
│       └── AIIntegrationService.get_status()                        │
│             returns AIStatus(                                      │
│                 model,             # canonical                     │
│                 override_model,    # dev env, if set               │
│                 live_probe = {     # what's actually loaded        │
│                   ok, opencode_model                               │
│                 }                                                  │
│             )                                                      │
│                                                                    │
│  Settings UI:                                                      │
│   • Row 1: provider + source + connected_at + ✓Live                │
│   • Row 2: Model: <id> [Change]                                    │
│   • Drift banner when live_probe.opencode_model != model           │
│                                                                    │
│  CLI `cliff status`:                                             │
│   {                                                                │
│     model, canonical_model, opencode_model,                        │
│     drifted: true|false                                            │
│   }                                                                │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                       SPAWN PATH (workspace)                       │
│                                                                    │
│  pool.start(ws_id, ws_dir)                                         │
│   ├── env_resolver()   → reads warm env cache                      │
│   │    {                                                           │
│   │      ANTHROPIC_API_KEY  | OPENROUTER_API_KEY | …,              │
│   │      *_BASE_URL  (when BYOK proxy or Ollama),                  │
│   │      OLLAMA_BASE_URL  (Ollama only),                           │
│   │    }                                                           │
│   ├── model_resolver() → reads warm model cache                    │
│   │    (canonical app_setting → catalog default fallback)          │
│   ├── _reconcile_opencode_model(ws_dir, model)                     │
│   │    writes ws/opencode.json so OpenCode's per-workspace         │
│   │    config matches the singleton's                              │
│   └── spawn OpenCode subprocess with scrubbed host env             │
└────────────────────────────────────────────────────────────────────┘
```

### Cache discipline

* `app.state.ai_env_cache` and `app.state.ai_model_cache` are warmed at
  boot and refreshed by the `on_key_change` hook. The pool reads from the
  cache; nothing on the spawn hot-path hits the DB or the vault.
* `app.state.ai_provider_credential_ok` is set by `verify_active_credential`
  during `_refresh_ai_env_cache`. Only `auth_failed` flips readiness off
  — network blips, rate limits and billing errors leave it untouched so
  the signal doesn't flap on a transient probe.

### Frontend cache

`useAIProviderStatus` polls every 15s with a 5s `staleTime` so the drift
banner shows up within roughly one refresh cycle of upstream change.
Every mutation invalidates the status key explicitly so post-save UI
updates are immediate.

## Consequences

**Positive**

* One source of truth for "current model" — drift is now an observable
  state, not a silent bug.
* Switching providers can no longer leave a stale model id behind.
* Google + Ollama are first-class providers without us writing any
  provider-specific SDK code — OpenCode handles the API calls.
* CLI and UI agree byte-for-byte (both go through the same service).

**Negative / accepted**

* `CLIFF_AI_MODEL_OVERRIDE_*` keeps a niche role for CI/dev pinning.
  This is intentional but slightly weakens the "one source" rule — we
  accept it because the env-var path is invisible to non-operators.
* The drift banner depends on the singleton being reachable. If it's
  down we show the canonical model and a `Live` indicator that fails
  silently — the user sees that the connection is unhealthy but not
  that a drift might exist. Tradeoff: a banner that fires on
  singleton-down would flap during restarts.
* `app_setting(key="model")` semantics change subtly — it's now
  authoritative rather than advisory. Existing rows with a stale
  provider prefix are ignored rather than honored, and the catalog
  default fills in. Operators who relied on the prefix-mismatch ambiguity
  (none observed) would need to update.

## Migration

Existing installs preserve the user's choice. Specifically:

* If `app_setting(model)` exists and its prefix matches the active
  provider, it is honored (no rewrite).
* If `app_setting(model)` exists with a stale prefix, it is ignored —
  the workspace spawns with the catalog default for the active provider.
  No automatic rewrite: the next BYOK save (or the picker) will set it
  correctly.
* The Anthropic default changes from `claude-sonnet-4-6` to
  `claude-haiku-4-5`. Existing Sonnet users are unaffected (their stored
  setting wins). New Anthropic BYOK lands on Haiku — they can switch via
  the picker.

## Test coverage

* `tests/test_ai_catalog.py` — new providers, env-var-set parity,
  default model ids.
* `tests/test_ai_service.py` — atomic provider+model write, `set_model`
  prefix validation, drift-state status payload, base-URL injection,
  Ollama keyless path, `verify_active_credential` per provider.
* `tests/test_ai_validators.py` — Google AI Studio probe + Ollama
  `/api/tags` probe.
* `tests/test_routes_ai_integrations.py` — `PUT /model`,
  `GET /models?provider=X`, BYOK route forwarding the `model` field.
* `tests/test_ai_provider_status.tsx` — drift banner appears when
  `live_probe.opencode_model != model`, picker invalidates the status
  key on save.

---

## 2026-05-17 update — Drop live-probe + drift signal (post-Q01 architect review)

The original implementation surfaced THREE reads on the wire
(`model`, `override_model`, `live_probe.opencode_model`) and rendered a
drift banner + Reconcile button to reconcile the latter two against the
canonical first. The Q01 architect health-check flagged this as
**violating the ADR's own "one read" rule**: the drift the probe could
detect was its own caching, not real product state — the
`on_key_change` hook synchronously restarts the singleton OpenCode on
every canonical-state write, so canonical state and the loaded model
cannot disagree by more than one event loop tick.

**Removed:**

* `LiveProbe` Pydantic model.
* `AIStatus.live_probe` and `AIStatus.override_model` wire fields.
* `_cached_live_probe` TTL cache + `asyncio.Lock` + module globals
  (~50 LOC).
* `invalidate_live_probe()` and every call site.
* `DriftBanner` React component + `Reconcile` button
  (`AIProviderStatus.tsx`).
* The CLI's `drifted` / `canonical_model` / `opencode_model` /
  `model_drift` blocker fields from `cliff status` JSON output.
* `AIProviderStatus.drift.test.tsx`.

**Updated read shape (canonical):**

```python
AIStatus(
    state, provider, source, connected_at, metadata,
    model,   # canonical, the ONE read
)
```

**Why this is safe:** the `on_key_change` hook fires synchronously on
every `save_byok` / `complete_oauth` / `adopt_detected` / `set_model`
and `disconnect`. It refreshes the env cache, refreshes the model
cache, rewrites the singleton's `opencode.json`, and restarts the
singleton OpenCode — all inline before the originating request
returns. There is no window in which canonical state and the
singleton's loaded model can drift.

**Env-override escape hatch:** `CLIFF_AI_MODEL_OVERRIDE_*` still
exists as a dev/CI knob (read by `catalog.resolve_model`) but is no
longer surfaced on the wire. Operators who want a global override use
the picker.

**OpenRouter default model change (L5):** the default moved from
`openrouter/tencent/hy3-preview` to `openrouter/anthropic/claude-haiku-4.5`.
A preview tag is a single point of failure for first-run UX — if the
provider pulls the preview, every new install 404s. Tencent Hy3 stays
available via the picker for cost-sensitive operators.

**Picker registry moved (M10):** `_SUGGESTED_MODELS` (cloud-provider
picker rows) moved from `api/routes/ai_integrations.py` to
`ai/catalog.py` next to `ProviderInfo` — same kind of static provider
metadata.
