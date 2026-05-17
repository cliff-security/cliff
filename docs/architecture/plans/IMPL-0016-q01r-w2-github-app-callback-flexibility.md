# IMPL-0016: Q01R Wave 2 — GitHub App install callback flexibility + manual recovery

**Scope:** Wave 2 (Q01R-W2) bug fix — GitHub App install pathway
**Bug:** B33 (P0)
**Owner:** App Builder (V2) — `backend/opensec/integrations/github_app/`, `backend/opensec/api/routes/`, `frontend/src/components/`, docs
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

The `opensec-local-test` GitHub App has its **Setup URL** hardcoded to `http://localhost:8000/api/integrations/github/setup`. This is a global per-App setting on github.com — it can't vary per installation or per device. After clicking "Install" in onboarding and picking an org on github.com, GitHub redirects to that exact URL with `?installation_id=…&setup_action=install&state=…`. Any Cliff deployment NOT bound to host port 8000 receives nothing; if the user happens to have another instance on :8000, that other instance silently consumes the install.

**Simplest correct fix is two-sided and small:**

1. **Backend recovery endpoint** — accept the install via a manual paste (`POST /api/integrations/github/setup/manual` with `{installation_id, state}`). This is the same code path the GET callback uses; we just expose it for the recovery flow.
2. **UI recovery flow** — after clicking Install, poll `/api/integrations/github/status` for 30 s; if it never flips to `connected` (no callback received), show a "Couldn't detect your install — paste your installation ID here" box. The user reads the ID off the GitHub URL or off the App's installation page.

**Why not change the App's Setup URL on github.com?** Because that requires every operator running their own App to keep the URL pinned to a specific port. The hosted Cliff in production will have a stable URL (e.g., `https://app.cliff.dev/...`). Local/dev/Docker-on-arbitrary-port deployments are where the gap is — and a UI recovery flow handles every variant without forcing operator config.

## Root causes (grounded in code)

| Layer | File:line | Issue | Required change |
|---|---|---|---|
| App config | github.com `opensec-local-test` settings | Setup URL hardcoded to `http://localhost:8000/...` | No change (the App stays as-is; recovery flow handles non-default ports) |
| Backend route | `backend/opensec/api/routes/ai_integrations.py` (and/or `github_app` module) | `GET /api/integrations/github/setup` is the only entry point; no path for users who didn't get the GET callback | Add `POST /api/integrations/github/setup/manual` that takes `{installation_id, state}` body and runs the same registration logic; CSRF-checks against `state` |
| UI | `frontend/src/components/ai-provider/` or `frontend/src/pages/OnboardingConnect.tsx` (grep) | After Install click, UI shows "Pick up where you left off" forever | Add `useEffect` that polls `/api/integrations/github/status` for 30 s; on timeout (still `installation_pending`), show "Couldn't detect your install" recovery card with an installation_id input |
| Docs | `docs/guides/setup-github-app.md` | Missing the "what if GitHub redirected me to the wrong URL" troubleshooting | Add a Troubleshooting section pointing at the recovery flow |

## Files touched

Backend (V2):
- `backend/opensec/integrations/github_app/flow.py` — factor the shared install-registration logic out of the GET callback so it can be called from both GET and POST entry points (if not already factored)
- `backend/opensec/api/routes/ai_integrations.py` (or wherever GitHub routes live) — add `POST /api/integrations/github/setup/manual`; reuses the same registration call as GET callback
- `backend/tests/test_routes_github_setup.py` — add manual-setup tests

Frontend (V2):
- `frontend/src/components/ai-provider/GitHubAppInstall.tsx` (or equivalent — grep for the Install button) — after the popup opens, start a 30 s poll; on timeout, render `<ManualRecoveryCard>` with an installation_id input + state hidden field
- `frontend/src/api/githubIntegration.ts` (or similar) — `useGitHubInstallStatus` hook for the poll
- `frontend/src/components/ai-provider/__tests__/` — extend tests

Docs:
- `docs/guides/setup-github-app.md` — Troubleshooting section: "If GitHub redirected you to localhost:8000 but your Cliff is on a different port: open the App's installation page on GitHub, copy the installation ID from the URL, paste it into Cliff's recovery form."

## Test plan (TDD-first)

Backend (pytest):
- `test_routes_github_setup.py::test_manual_setup_registers_install_with_valid_state` — POST `{installation_id: 12345, state: <valid>}` → 200, install row created, status flips to `connected`
- `test_routes_github_setup.py::test_manual_setup_rejects_invalid_state` — POST with mismatched state → 400 CSRF rejection
- `test_routes_github_setup.py::test_manual_setup_idempotent` — POSTing the same install twice doesn't create duplicate rows

Frontend (Vitest):
- `GitHubAppInstall.test.tsx::test_polls_status_after_install_click` — assert poll fires every ~3 s
- `GitHubAppInstall.test.tsx::test_shows_recovery_card_after_30s_timeout` — assert `<ManualRecoveryCard>` renders if status never flips
- `GitHubAppInstall.test.tsx::test_recovery_card_submission_calls_setup_manual` — assert form POSTs to `/api/integrations/github/setup/manual`

E2E (manual, Wave 3 QA):
- Fresh Docker on port 8088 → click Install → pick cliff-security on github.com → callback lands on `localhost:8000` (the user's other instance or 404) → return to Cliff tab → wait 30 s → see recovery card → paste install_id from the redirect URL → status flips to `connected`

## Risks

- **Backend route deduplication.** The GET and POST entry points must share the same registration code; if they diverge, manual-recovery installs could be malformed. Mitigation: factor the shared logic into one helper, both routes call it.
- **CSRF protection on the manual path.** The recovery card must include the `state` value from the original `/connect` call. If we drop state validation here, an attacker who tricks the user into pasting an attacker-controlled `installation_id` could bind a fake install. Mitigation: validate state same as GET callback.
- **30 s timeout might be too short for slow GitHub redirects.** Mitigation: make timeout configurable via prop, default 30 s; show the recovery card as "optional / alternate path" alongside a "still waiting…" spinner so users on slow networks don't get rushed.

## ADR amendment

See `docs/adr/0037-github-app-write-permissions.md` (will be amended in IMPL-0018) to add a section "Setup URL is per-deployment — recovery flow is mandatory for non-canonical deployments."

## Rollout

Single PR, 4 commits:
1. `feat(q01r-w2-github-app): factor install-registration logic`
2. `feat(q01r-w2-github-app): POST /setup/manual recovery endpoint (B33)`
3. `feat(q01r-w2-github-app): UI 30s poll + manual recovery card (B33)`
4. `docs(q01r-w2-github-app): document the recovery flow`

Target branch: `main`.
