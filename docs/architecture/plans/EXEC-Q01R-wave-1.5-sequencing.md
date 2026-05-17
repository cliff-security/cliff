# EXEC — Q01R (Wave 1.5) execution sequencing

**Date:** 2026-05-17
**Status:** Draft — needs CEO approval
**Goal:** Land all nine Q01R fixes (B22–B30) in one wave so the next QA re-run can drive a UI-only happy path to grade A.

## Bugs → plans → owners

| Bug | Sev | Plan | Owner |
|---|---|---|---|
| B22 — OAuth UI polling stale | P1 | IMPL-0012 | App Builder (V2) |
| B23 — Posture checks hardcoded to `main` | P1 | IMPL-0013 | App Builder (V2) |
| B24 — Auto-fix posture contract mismatch + silent UI fail | P0 | IMPL-0013 | App Builder (V2) |
| B25 — `/issues?severity=critical` URL filter ignored | P2 | IMPL-0012 | App Builder (V2) |
| B26 — "Review is clear" shown when 45 in Todo | P3 | IMPL-0012 | App Builder (V2) |
| B27 — Dashboard "Start" cards just navigate | P2 | IMPL-0012 | App Builder (V2) |
| B28 — Side panel "Thinking…" stays stale | P1 | IMPL-0012 | App Builder (V2) |
| B29 — No UI "Approve plan" button | P0 | IMPL-0012 (linked to B28 fix) | App Builder (V2) |
| B30 — GitHub App OAuth token can't push | P0 | IMPL-0014 + ADR-0037 | App Builder (V2) + Ops |

All nine bugs land within App Builder territory. Agent Orchestrator (V1) is not touched by this wave.

## Sequencing (smallest-blast-radius first)

The bugs are mostly independent, but two ordering rules matter:

1. **IMPL-0014 ops step before any QA re-run** — the GitHub App `opensec-local-test` must have its permission matrix updated on GitHub.com (Contents:write + Pull requests:write + Actions:read + Administration:read) per ADR-0037. This is a manual GitHub admin action; it can happen before, during, or after the code PR, but it must be done before Wave 2's QA re-run.
2. **B28 fix lands before / with B29 fix** — the Approve button already exists in `DefaultFooter` at stage `plan_ready`; B29's "missing button" symptom is downstream of B28's stale polling. Doing them in the same PR keeps the diff coherent.

Recommended PR order:

1. **PR-Q01R-A (IMPL-0013):** Posture autofix contract + default-branch fix
    - Smallest diff, lowest coupling, makes the dashboard's "Auto-fix" promise honest immediately
    - 2 commits: `fix(q01r-posture): shrink autofix registry + surface 4xx in UI`, `fix(q01r-posture): resolve default branch from repo metadata`
2. **PR-Q01R-B (IMPL-0014 + ADR-0037 ops step):** Push-token preflight + App permissions doc + GitHub App admin change
    - Unblocks executor PR creation on org repos
    - 1 commit + 1 manual ops step (out-of-band)
3. **PR-Q01R-C (IMPL-0012):** UI reactivity + plan-approval flow + Issues UX polish
    - Largest diff, but most of it is in `IssueSidePanel.tsx` and `IssuesPage.tsx`; the actual hot path is small
    - 4 commits: `fix(q01r-ui): always poll workspace agent runs`, `fix(q01r-ui): approve-then-execute footer`, `fix(q01r-ui): hydrate Issues filters from URL`, `fix(q01r-ui): dashboard gate cards deep-link to side panel`, `fix(q01r-ui): tighten Review-is-clear card visibility`

All three PRs target branch `main` (the Wave 1.5 collection branch). CEO merges to `main` after Wave 2 re-run passes.

## Exit criteria (Wave 2 must verify)

Re-run the same UI-only QA flow that found B22–B30 (fresh Docker, fresh DB, no CLI, Claude in Chrome). The release ships when:

- All nine bugs are gone (each per-bug report's "Recreate" steps no longer reproduce)
- A new user can onboard → connect repo → connect OpenRouter → trigger assessment → see dashboard → click "Approve & generate fix" on a Critical → real PR appears in the target repo — without ever touching the CLI or curl
- Dashboard grade goes from F to at least D on NodeGoat after merging the agent-generated PRs (B14 from Wave 1 verifies the close-after-merge reconciliation)

## What's explicitly out of scope this wave

- New agent templates for `code_owners_exists` and `actions_pinned_to_sha` posture fixes (tracked as separate BACKLOG items — covered by IMPL-0013 follow-up section)
- Switching from user OAuth tokens to installation access tokens (covered by ADR-0037 alternatives section)
- B14 from Wave 1 (hollow close) — already fixed; the B14 symptom in this re-run was caused by B30 (push failed) and disappears when B30 is fixed
- SSE for live agent-run updates — chose 5s polling as the simplest correct fix; SSE is a follow-up if polling cost becomes an issue

## Tracking

Tasks added to `docs/BACKLOG.md` under App Builder (V2). Each PR closes its corresponding tasks.
