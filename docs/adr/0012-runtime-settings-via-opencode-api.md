# ADR-0012: Runtime settings via OpenCode API

**Date:** 2026-03-27
**Status:** Accepted

## Context

The Settings page was read-only — it displayed the model name, engine status, and OpenCode version, but nothing was configurable. Users had to manually edit `opencode.json` and restart the backend to change models, and set environment variables for API keys. This was impractical for Docker/remote deployments.

We also had a separate, empty Integrations page that served no purpose.

## Decision

### Use OpenCode's runtime API for instant configuration

Instead of restarting the OpenCode subprocess on config changes, we use its REST API:

- **`PATCH /config`** — Update model at runtime (instant, no restart needed)
- **`PUT /auth/{providerID}`** — Set API keys at runtime via `{ type: "api", key: "..." }`
- **`GET /provider`** — List all 105 available providers with model catalogs
- **`GET /config/providers`** — List providers with active credentials (from env vars or UI)
- **`GET /provider/auth`** — List available auth methods per provider

### Dual persistence for API keys

Keys set via the UI are:
1. Sent to OpenCode immediately via `PUT /auth/{id}` for instant effect
2. Stored in the `app_setting` SQLite table (masked) for persistence across restarts
3. Re-injected to OpenCode on startup via `restore_keys_to_engine()`

Keys from environment variables (e.g., `OPENAI_API_KEY`) are detected via `GET /config/providers` and displayed with a lock icon — no DB storage needed.

### Merge Integrations into Settings

The Integrations page was absorbed into Settings as a section. The `/integrations` route redirects to `/settings`. Navigation was simplified from 4 items to 3 (Queue, Workspace, History) plus Settings at the bottom.

### Provider-centric UI

Model selection and API key configuration are combined into a single provider-centric flow:
- The active provider/model/auth is shown at the top
- A search box below lets users find providers and models
- Search results show auth status and model buttons inline

### Config file sync

When the model is changed via the UI, both `opencode.json` and the `app_setting` DB table are updated. On startup, the backend reconciles any drift between them.

## Consequences

**Easier:**
- Changing models is instant — no restart, no file editing
- API keys can be configured from the browser (critical for Docker deployments)
- Single page for all configuration
- Env-var-based keys are detected and displayed automatically

**Harder:**
- Keys set via `/auth` are forgotten by OpenCode on restart — mitigated by `restore_keys_to_engine()`
- `opencode.json` can drift from runtime state — mitigated by `reconcile_model()` on startup
- 105 providers could overwhelm the UI — mitigated by search-only (no full list displayed)

## Key files

| File | Purpose |
|------|---------|
| `backend/cliff/engine/client.py` | OpenCode REST client (config, provider, auth endpoints) |
| `backend/cliff/engine/config_manager.py` | Orchestrates config changes (API + DB + file) |
| `backend/cliff/api/routes/settings.py` | Settings REST endpoints |
| `backend/cliff/db/repo_setting.py` | App settings DB repository |
| `backend/cliff/db/repo_integration.py` | Integration config DB repository |
| `frontend/src/components/settings/ProviderSettings.tsx` | Unified provider/model/auth UI |
| `frontend/src/components/settings/IntegrationSettings.tsx` | Integration management UI |
