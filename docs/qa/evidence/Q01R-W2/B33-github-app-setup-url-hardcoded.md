# Q01R-W2-B33 — GitHub App setup_url hardcoded to localhost:8000 breaks any non-default-port deployment

**Severity:** P0
**Surface:** GitHub App config + backend (silent acceptance of wrong-port setup)

## What I observed
Built and ran a fresh Cliff Docker on port 8088 (mapped to container 8000) for a clean Wave 2 QA. Clicked the GitHub App Install in the new Cliff's onboarding, picked cliff-security org, clicked Install.

GitHub redirected to:
```
http://localhost:8000/api/integrations/github/setup?installation_id=133155706&setup_action=install&state=GzOkqZ...
```

**Note port 8000 — not 8088.** Chrome showed an error page because:
- The user's previous wave-1 Cliff instance was also running on port 8000 (still alive from earlier in the session)
- That instance received the install callback
- The fresh wave-2 instance on port 8088 was never notified

If the user had nothing on port 8000 the browser would have shown a connection-refused; either way the fresh deployment can't ever complete onboarding.

## Root cause
The GitHub App `opensec-local-test` has its **Setup URL** registered as `http://localhost:8000/...` on github.com. This URL is global per-App and can't vary per installation or per device. Any deployment that doesn't bind container port 8000 to host port 8000 (every Docker remap, every dev parallel-stack, every reverse-proxied install) breaks.

## Impact
- Any user who has another OpenSec instance on :8000 (very common for devs) gets their fresh install silently registered on the wrong instance
- Any user with nothing on :8000 just sees a "connection refused" page after clicking Install — no path forward
- Docker compose users who use a non-default port for any reason (collision avoidance) all hit this
- Combined with B31's vault-silently-broken-on-URL-safe-key, brand new users get hit by two P0s before even reaching the AI step

## Three layered fixes

### B33a — GitHub App config (immediate)
Either:
- Leave Setup URL blank (GitHub redirects to the App's homepage; Cliff can detect install via webhook + ask the user to paste install_id), OR
- Set it to a dispatch endpoint that's configured per deployment (e.g. `https://opensec.example.com/setup` for the hosted version)

For local dev specifically, leaving it blank is best — the install completes on github.com and Cliff polls/detects via its existing `/api/integrations/github/status` endpoint.

### B33b — backend (defensive)
Add a route that accepts `installation_id` from a manual paste or query param, so a user who hits the wrong-port issue can recover:
```
POST /api/integrations/github/setup?installation_id=<id>  → looks up install via App auth, registers, done
```
The route already exists (`GET /api/integrations/github/setup`) — the existing implementation may already work, just needs to be reachable independently of the GitHub redirect.

### B33c — UI
After clicking Install, the onboarding step should poll for install completion (via `/api/integrations/github/status`) and time out with a clear "If GitHub redirected you to localhost:8000 instead of this URL, paste your installation ID here: [____]" recovery flow. Today the UI just sits at the Install screen forever.

## Workaround for the QA
Manually call the setup endpoint on the wave-2 instance:
```
curl http://localhost:8088/api/integrations/github/setup?installation_id=133155706&setup_action=install
```
Then continue.

## Evidence
- Browser address bar after Install: `http://localhost:8000/api/integrations/github/setup?installation_id=133155706&setup_action=install&state=GzOkqZ_fsoIOwk7hQKdovR-dJsdveWg6`
- Wave-2 backend logs show NO setup callback received (just the earlier `connect` POST that initiated the device flow)
