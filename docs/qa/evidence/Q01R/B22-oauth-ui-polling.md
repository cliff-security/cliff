# Q01R-B22 — OpenRouter OAuth: UI stays in "Waiting for you to authorize" after callback succeeds

**Severity**: P1
**Surface**: UI (frontend onboarding step 2)

## What I observed
1. Clicked "Connect with OpenRouter" → opened openrouter.ai auth page in a new tab.
2. Authorized → callback page rendered at `http://localhost:3000/callback?code=...` ("You can close this tab. OpenSec received the authorization.")
3. Returned to Cliff onboarding tab — UI still spinning on "Waiting for you to authorize on openrouter.ai..." with link "Open authorization page again".
4. Manually navigated to `/onboarding/ai` (reload) — only then did the UI flip to "Connected to OpenRouter".

## Evidence
- Docker log shows `AI integration saved for provider openrouter via openrouter-oauth` at 12:45:50
- `GET /health` returns `ai_provider_ready: true` and `model: openrouter/anthropic/claude-haiku-4.5`
- But UI continued polling `/api/integrations/ai/openrouter/status?session_id=...` and never picked up completion until manual reload

## Root cause hint
Frontend polling loop terminates without re-reading status after the parent tab regains focus, OR the status endpoint doesn't return "complete" after the cred was already saved. Check `frontend/src/components/ai-provider/OpenRouterOAuthStep.*` and the `/api/integrations/ai/openrouter/status` handler.

## Impact
First-touch experience. User authorizes correctly, sees a working callback, returns to the app — and the app appears broken. Many users will hit "Open authorization page again" and re-trigger the OAuth.
