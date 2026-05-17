# Settings configuration

Cliff's Settings page lets you configure AI providers, models, API keys, and integrations from the browser. All changes take effect immediately — no restart required.

## Accessing settings

Navigate to **Settings** via the gear icon at the bottom of the side navigation, or go to `/settings` directly.

## Providers and models

The top card shows your current provider, model, and authentication status.

### Changing the model

1. Use the **search box** under "Change provider or model"
2. Type a provider name (e.g., "anthropic") or model name (e.g., "claude", "gpt-4")
3. Matching providers appear with their available models
4. Click a model button to switch — the change is instant

Models use the `provider/model-id` format (e.g., `openai/gpt-4.1-nano`, `anthropic/claude-sonnet-4-20250514`).

### Model capabilities

Model buttons show capability flags:
- **R** — Reasoning (extended thinking)
- **T** — Tool use (function calling)

## API keys

### Environment variables (recommended for production)

Set provider API keys as environment variables before starting Cliff:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

These are detected automatically and shown in Settings with a lock icon and "Configured via environment" label.

### Setting keys via the UI

For Docker or remote deployments where env vars are inconvenient:

1. Find your provider in the active configuration card or via search
2. Click **Set key** (or **Update** to change an existing key)
3. Paste your API key and press Enter or click Save
4. The key takes effect immediately — no restart needed

Keys set via the UI are:
- Stored in the Cliff database (masked — only last 4 characters visible)
- Sent to the OpenCode engine at runtime
- Automatically re-injected if the engine restarts

### Key priority

If both an environment variable and a UI-configured key exist for the same provider, the environment variable takes precedence.

## Integrations

The Integrations section manages connections to external systems:
- **Vulnerability scanners** (e.g., Snyk, Qualys)
- **Ownership context** (e.g., PagerDuty, ServiceNow)
- **Ticketing systems** (e.g., Jira, Linear)
- **Validation tools** (e.g., SonarQube)

Each integration can be enabled/disabled with a toggle and removed with the delete button.

## API endpoints

Settings are also available via the REST API:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/settings/model` | Current model config |
| `PUT` | `/api/settings/model` | Change model |
| `GET` | `/api/settings/providers` | All available providers |
| `GET` | `/api/settings/providers/configured` | Providers with credentials |
| `GET` | `/api/settings/api-keys` | Stored API keys (masked) |
| `PUT` | `/api/settings/api-keys/{provider}` | Set API key |
| `DELETE` | `/api/settings/api-keys/{provider}` | Remove API key |
| `GET` | `/api/settings/integrations` | List integrations |
| `POST` | `/api/settings/integrations` | Add integration |
| `PUT` | `/api/settings/integrations/{id}` | Update integration |
| `DELETE` | `/api/settings/integrations/{id}` | Remove integration |

## Docker deployment

When running in Docker, pass API keys as environment variables:

```bash
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -v cliff-data:/data \
  cliff
```

Or configure them via the Settings UI after the container starts.
