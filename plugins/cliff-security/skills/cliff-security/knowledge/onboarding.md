---
name: "onboarding"
description: "Configure the two credentials Cliff needs — an AI provider key (for the LLM-backed agents) and a GitHub Integration (for posture probes and PR-driven remediation)."
version: "0.2.0"
---

# Onboarding

Engage when:

- The user asks to "connect GitHub", "add my API key", "set up the model", "onboard", "configure providers".
- `cliffsec status` exits 0 with `ready: false` and `blockers` includes `no_llm_model_configured` and/or `no_github_integration`.
- Hand-off from `install.md` step 4 when status reported `ready: false`.

## What Cliff needs (and why)

Cliff requires **two** credentials to drive the full remediation loop. Either alone is not enough.

| Credential | Why | Storage |
|---|---|---|
| **AI provider key** (OpenAI / Anthropic / OpenRouter / Google / Ollama / custom) | The agent pipeline (enricher, planner, validator) is LLM-backed. Without a key, every workspace stalls at the first agent run. | Either env var at daemon boot, or encrypted vault via `POST /api/integrations/ai/byok`. The active model is set via `cliffsec model set <provider>/<id>`. |
| **GitHub Integration** (a PAT stored as an Integration row) | Posture probes (`branch_protection_enabled`, `secret_scanning_enabled`, `no_stale_collaborators`, `actions_pinned_to_sha`, …) hit the GitHub API. Remediation PRs also need write access. Without it, every posture check returns `unknown` and the grade caps at C. | Encrypted vault row, created via `POST /api/settings/integrations` (adapter_type=`github`) + `POST /api/settings/integrations/{id}/credentials`. **The daemon does NOT read `GITHUB_TOKEN` from the env.** |

## Hard rules recap (from SKILL.md)

- Storing an API key or creating an Integration is a write action. Get explicit "yes" before running the `curl -X POST/PUT` calls.
- Never echo a PAT or API key into chat output. Show it once back to the user only if they ask to verify what you stored.

## The onboarding flow

### 1. Inspect what's already configured

These are read-only — fine to run unprompted:

```bash
# AI provider — env-sourced or vault-sourced are both fine. ``state`` is
# ``connected`` once a key is in place, ``unconfigured`` otherwise.
curl -s http://localhost:8000/api/integrations/ai/status

# Active model (defaults to openai/gpt-5-nano if unset)
cliffsec model get

# GitHub Integration — must have one row with adapter_type=github
curl -s http://localhost:8000/api/settings/integrations | jq '.[] | select(.adapter_type=="github")'
```

Decide what's missing:

- `state: unconfigured` AND no relevant env var → AI provider missing.
- No github Integration row → GitHub missing.
- Both present → re-run `cliffsec status`. If it's still `ready: false`, route to `troubleshooting.md` — onboarding isn't the blocker.

### 2. AI provider key — if missing

Ask the user which provider they want to use. The three onboarding tiers (per ADR-0035):

- **Tier 1 — Auto-detect.** If `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` is set in their shell, or if `~/.claude/.credentials.json` / `~/.aider/.env` / `~/.config/openai/` exist, the daemon picks it up at boot. Suggest `cliffsec restart` if they've just set an env var and want the daemon to re-detect.
- **Tier 2 — OpenRouter OAuth.** One command: have the user open `http://localhost:8000/api/integrations/ai/openrouter/start` in a browser. The backend runs the PKCE handshake on `localhost:3000`. Two clicks, no key paste.
- **Tier 3 — Direct BYOK.** User supplies a key. Confirm "may I store this in Cliff's encrypted vault?" then:

```bash
curl -X POST http://localhost:8000/api/integrations/ai/byok \
  -H "Content-Type: application/json" \
  -d '{"provider":"<provider>","api_key":"<paste>"}'
```

`<provider>` is one of: `openai`, `anthropic`, `openrouter`, `google`, `ollama`, `custom`. The backend validates the key against the provider before persisting; a bad key returns `400` with an `auth_failed` detail.

After storing the key, set the active model:

```bash
cliffsec model set <provider>/<model-id>
```

Reasonable defaults per provider (from ADR-0037):

| Provider | Default model |
|---|---|
| OpenRouter | `anthropic/claude-haiku-4.5` |
| Anthropic | `claude-haiku-4-5` |
| OpenAI | `gpt-5` |
| Google | `gemini-2.5-flash` |
| Ollama | user picks from `/api/tags` |

### 3. GitHub Integration — if missing

This requires a personal access token. Two paths:

- The user already has one (or you can grab `gh auth token` from their gh CLI). Confirm before reading it.
- The user doesn't have one. Give them the URL https://github.com/settings/tokens/new and the scope list (below). They paste it back.

**Required scopes for the posture probes:**

| Scope (classic PAT) | What it unlocks |
|---|---|
| `repo` | Branch protection read, secret-scanning settings read, dependabot alerts read, PR write |
| `read:org` | Collaborator audit (for `no_stale_collaborators`) |

Fine-grained PATs work too: Contents read, Metadata read, Administration read, Code scanning alerts read, Pull requests read+write, on the target repo.

Once you have the PAT and explicit user approval, create the Integration row and store the credential:

```bash
# 1. Create the integration row (the repo_url here is the default target;
#    individual scans can override it).
INT_ID=$(curl -s -X POST http://localhost:8000/api/settings/integrations \
  -H "Content-Type: application/json" \
  -d '{"adapter_type":"github","provider_name":"GitHub","enabled":true,
       "config":{"repo_url":"<https://github.com/owner/repo>"},"action_tier":1}' \
  | jq -r .id)

# 2. Store the PAT in the encrypted vault, keyed under the integration row.
curl -X POST "http://localhost:8000/api/settings/integrations/${INT_ID}/credentials" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg v "$PAT" '{key_name:"github_personal_access_token", value:$v}')"
```

`$PAT` is a shell variable you set just before — don't put the PAT literal in the JSON body in chat.

### 4. Re-verify

```bash
cliffsec status
```

Expect exit 0 + `ready: true`. If still `ready: false`, read the `blockers` field:

- `no_llm_model_configured` → step 2 didn't take. Check `cliffsec model get`, check `curl /api/integrations/ai/status`.
- `no_github_integration` → step 3 didn't take. Check `curl /api/settings/integrations | jq '.[] | select(.adapter_type=="github")'`.
- Anything else → `troubleshooting.md`.

### 5. Hand off

After `ready: true`, tell the user "onboarding done — Cliff is ready to scan" and route them to `secure-repo.md` if they originally asked to secure a repo, or stop if they only asked to onboard.

## What NOT to do

- Don't onboard a provider key the user hasn't explicitly named. If they say "set me up", ask which provider — don't default to `openai` silently.
- Don't auto-create the GitHub Integration with `gh auth token` without surfacing what scopes that token has. The user's `gh` token may be over- or under-scoped for Cliff's needs.
- Don't echo the stored key back to confirm. Trust the API's response code; re-fetch via `GET /api/integrations/ai/status` if you really need to verify.
- Don't store the PAT as an env var (`GITHUB_TOKEN`). The daemon ignores it — it only resolves the token from the encrypted vault via the Integration row.

## Token discipline

- Don't dump the full `GET /api/settings/integrations` response if it has 20 rows. Pipe it through `jq '.[] | select(.adapter_type=="github")'` to get the one you care about.
- One re-run of `cliffsec status` is enough to confirm readiness. Don't poll.
