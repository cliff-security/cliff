# Q01R-W2-B34 — GitHub rejects every device-code Cliff issues ("Uh oh, we couldn't find anything")

**Severity:** P0 (blocks the recommended onboarding path)
**Surface:** GitHub App config (likely) + backend (silent on the symptom)

## What I observed
After resolving B31 (vault key) and B33 (setup_url), the device-code flow itself fails:
1. Cliff calls `POST https://github.com/login/device/code` → 200 OK, gets user_code `24DF-30EF`
2. I enter `24DF-30EF` on `https://github.com/login/device` while signed in as galanko
3. GitHub responds: **"Uh oh, we couldn't find anything"** and redirects to `/login/device/failure?reason=not_found`

Verified:
- Cliff's stored `client_id` (`Iv23lio5AYwdYwkcI90e`) matches `gh api /apps/opensec-local-test --jq .client_id` exactly
- `device_code_expires_at: 2026-05-17T15:33:26Z`, entered the code at ~15:21 (well before expiry)
- Issued a fresh code by clearing the DB and re-calling `/connect` — same rejection
- Cliff continues polling `/login/oauth/access_token` and gets 200 OK back (so the device_code IS valid on GitHub's side, just the user_code path doesn't resolve)

## Most likely root cause
The GitHub App `opensec-local-test` does not have **"Enable Device Flow"** turned on under General → Identifying and authorizing users. Without that toggle, GitHub Apps can still call `/login/device/code` (the endpoint succeeds), but the user_code can't be resolved at `/login/device` — exactly the symptom we see.

The other plausible root cause is a GitHub-side regression on user-to-server device-flow for Apps in this state, which we can rule in/out by checking the toggle.

## Manual ops fix (matches ADR-0037's "App config" pattern)
On github.com, in `Opensec local test` App settings:
- Enable **Device Flow**: ON
- (re-)Verify: Contents:write, Pull requests:write, Metadata:read

After flipping that toggle, re-run the onboarding flow.

## Backend gap (silent error)
Cliff's `/api/integrations/github/status` endpoint reports `status: installation_pending` while polling, never times out, and never surfaces this specific failure mode. The user sees the device-code on screen, GitHub rejects it, and Cliff just keeps polling forever waiting for an authorization that can't happen.

**Suggested:** when GitHub returns `slow_down` / `expired_token` / `access_denied` on the polling endpoint, surface that to the UI as a terminal error with a remediation link to the App's "Enable Device Flow" docs.

## Workaround for this QA
Switch to the PAT onboarding path (the documented alternative under "Prefer a personal access token? Use one →"). The PAT path uses the user's own access token directly and bypasses the App device flow entirely.
