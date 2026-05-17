# EXEC — Q01R Wave 2 execution sequencing

**Date:** 2026-05-17
**Status:** Draft — needs CEO approval
**Goal:** Land all five Q01R-W2 fixes (B31, B32, B33, B35a, B35b, B35c) in one wave so Wave 3 QA can drive a UI-only happy path to a real PR. (B34 is deferred — flaky, needs reproduction data first.)

## Bugs → plans → owners

| Bug | Sev | Plan | Owner |
|---|---|---|---|
| B31 — vault rejects URL-safe base64 silently | P0 | IMPL-0015 | App Builder (V2) |
| B32 — vault init exception swallowed | P1 | IMPL-0015 | App Builder (V2) |
| B33 — GitHub App setup_url hardcoded | P0 | IMPL-0016 | App Builder (V2) |
| B35a — preflight consults wrong source of truth | P1 | IMPL-0017 | App Builder (V2) |
| B35b — UI header stays stale past terminal error | P1 | IMPL-0017 | App Builder (V2) |
| B35c — no proactive push-access diagnostic | P1 | IMPL-0018 | App Builder (V2) |
| B34 — device-flow Authorize flaky | P2 | — (deferred) | App Builder (V2) — track in BACKLOG, file follow-up if it reproduces |

All Wave 2 bugs land within App Builder territory. No Agent Orchestrator (V1) work needed.

## Sequencing (smallest-blast-radius first)

Three rules drive ordering:

1. **IMPL-0015 first** — tiny, no dependencies, unblocks every fresh-Docker QA going forward (including Wave 3's own setup). The Wave 3 QA run literally fails on the first step without this fix.
2. **IMPL-0017 before IMPL-0018** — the diagnostic in 0018 *uses* the enhanced `check_repo_push_access` from 0017. Shipping 0018 first would leave the diagnostic giving the same false-positive signal that B35a already has.
3. **IMPL-0016 can ship anywhere in the order** — independent of the other three. Schedule it parallel to whichever else has bandwidth.

Recommended PR order:

1. **PR-Q01R-W2-A (IMPL-0015):** vault key UX + visible init errors
    - Closes B31 + B32
    - 2 commits; ~50 lines changed
    - Conventional commit prefix `fix(q01r-w2):`
2. **PR-Q01R-W2-B (IMPL-0016):** GitHub App callback flexibility
    - Closes B33
    - 4 commits; backend recovery endpoint + UI poll + recovery card + docs
    - Conventional commit prefix `feat(q01r-w2-github-app):`
3. **PR-Q01R-W2-C (IMPL-0017):** preflight teeth + UI terminal error
    - Closes B35a + B35b
    - 3 commits; backend preflight extension + frontend stage derivation + tests
    - Conventional commit prefix `fix(q01r-w2-preflight):` / `fix(q01r-w2-ui):`
4. **PR-Q01R-W2-D (IMPL-0018):** push-access diagnostic on Settings
    - Closes B35c
    - 3 commits; diagnose endpoint + Settings badge + docs
    - Conventional commit prefix `feat(q01r-w2-diagnose):`
    - Should land AFTER PR-Q01R-W2-C so the diagnostic surfaces accurate state

All four PRs target `main`.

## Exit criteria (Wave 3 must verify)

Re-run the same UI-only QA flow that found B31–B35 (fresh Docker, fresh DB, no CLI, Claude in Chrome). The release ships when:

- Vault initializes cleanly with either standard or URL-safe base64 keys; bad keys produce specific log lines (B31, B32)
- Onboarding completes without manual recovery, OR with manual recovery surfaced clearly if the App's setup URL doesn't match the deployment (B33)
- Settings page shows green "Push verified" badge before the user clicks Approve (B35c)
- Clicking Approve on a Critical with insufficient install perms returns 412 within a second; the side panel header transitions to "Needs attention" with a "Retry" button (B35a, B35b)
- A Critical with correct setup drives to a real PR on cliff-security/NodeGoat — the original promise of B30

## What's explicitly out of scope this wave

- B34 (device-flow Authorize flakiness) — needs reproduction data. Tracked as a BACKLOG follow-up; will file if it reproduces in Wave 3.
- Switching from user OAuth tokens to installation access tokens (the ADR-0037 alternative) — deferred until a use case for non-user-bound execution emerges (e.g., scheduled re-assessments).
- Changing the App's Setup URL on github.com — IMPL-0016 sidesteps this with a recovery flow; no operator forced into per-deployment App config.

## Tracking

Tasks added to `docs/BACKLOG.md` under App Builder (V2) as Q16–Q-N (continuing the Q1–Q15 numbering from Wave 1.5). Each PR closes its corresponding Q-tasks.
