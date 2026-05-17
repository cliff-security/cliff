# Q01 re-run (Wave 1.5) — UI-only on fresh Docker, latest main

**Date**: 2026-05-17
**Target**: cliff-security/NodeGoat (master branch)
**Environment**: docker `cliff:qa-rerun` built from main, port 8088, fresh volume, fresh credential key, no provider env vars
**Driver**: Claude in Chrome — UI only, cliff CLI forbidden per Wave 2 policy
**Provider**: OpenRouter OAuth → `openrouter/anthropic/claude-haiku-4.5` (auto-selected)
**GitHub**: galanko, Device-flow OAuth (installation_id=133122855, app "cliff-local-test")
**Branch**: `qa/q01-campaign-fixes` policy applied (would-be — current run was on main; Wave-2 to enforce)

## Headline verdict: RED (UI-only happy path is fully blocked)

Two P0 bugs in series prevent any UI-only user from producing a real remediation PR on this build:
- **B29** — no UI "Approve plan" button. Plan completes, user has no way forward without curl.
- **B30** — even when the executor is triggered (via curl bypass), it can't push because the GitHub App OAuth token lacks `contents:write` on the org repo.

Either alone is a release blocker. Together they sink the entire happy-path narrative in `docs/qa/QA-0001-Q01-security-value-nodegoat.md` for the UI-only configuration that Wave 2 is mandating.

## Wave-1 fixes verified
| Wave-1 bug | Verified now? | How |
|---|---|---|
| **B02** readiness gate lying | ✓ fixed | `/health` returns `ai_provider_ready:false` until OAuth completes, then flips to true |
| **B06** BYOK propagation | ✓ fixed | OAuth-flow key reaches subprocess, model auto-selects to claude-haiku-4.5 |
| **B08** hallucination tripwires | ✓ partial | The enricher output for minimist was clean (real CVE-2021-44906, real fixed-version 1.2.6); cross-check on a posture finding still pending |
| **B14** hollow close | ✗ regressed | Executor "completed" but pr_url stayed null (no actual PR was created, though for a different reason this time — B30) |
| **B17** 76s timeout | ✓ effective | Single-finding plan stage completed in ~60s, no timeouts |

## New defects (B22–B30)

| ID | Sev | Title | Surface |
|---|---|---|---|
| B22 | P1 | OAuth UI stays "Waiting for you to authorize" after callback succeeds | UI |
| B23 | P1 | Posture checks hit `branches/main` and `commits?sha=main` (404/403 on master-default repos) | backend |
| B24 | P0 | Auto-fix posture: frontend offers checks backend rejects (422); UI swallows the error silently | UI + backend |
| B25 | P2 | `/issues?severity=critical` URL param ignored on load | UI |
| B26 | P3 | "Review is clear" + green check shown when 45 issues are queued | UI |
| B27 | P2 | Dashboard "Start" cards navigate to filter view instead of driving the work | UI |
| B28 | P1 | Workspace side-panel "Thinking…" widget stays stale after agents complete | UI |
| **B29** | **P0** | **No UI affordance to approve the plan / trigger executor** | **UI** |
| **B30** | **P0** | **Executor push fails — GitHub App OAuth token lacks write scope on org repo** | **backend + App config** |

P0 + P1 cluster all in UI/UX layer except B23 + B30 — engine itself is sound for the parts that ran.

## What worked

These are real wins compared to Wave 1 — keep them:
- Onboarding flow (welcome → connect → AI → assess) is 3 clear screens, ~3 min as promised
- Repo picker is clean, GH device flow works, callback hits the Docker container correctly
- OpenRouter OAuth in Docker (port 3000 callback) works end-to-end — validates the recent fix (973d055)
- Assessment runs automatically from onboarding, dashboard appears with grade
- Dashboard "Level up to D" panel is excellent — gives concrete actionable next steps and the grading rubric is transparent
- Plan-stage agent quality is high: 95% confidence on the right CVE, right fixed version, right files
- Activity log inside side panel renders each agent run with confidence, duration, and summary

## What to fix before Wave 2 runs

In priority order:
1. **B29 + B30** — Wave 2 cannot run a UI-only campaign at all until these land.
2. **B24** — first thing a new user clicks is broken; fix the autofix contract and surface 4xx errors.
3. **B22 + B28** — fix the polling pattern across the app; the same root cause shows up in three places (OAuth, plan stage, executor stage).
4. **B23** — branch-name detection broken for any non-`main` default; trivial fix, prevents falsely-failing posture checks on older repos.
5. **B25, B26, B27** — UX polish, but B27 in particular hurts because it's the first interaction after onboarding.

## Files
- `evidence/Q01R/B22-*.md` through `B30-*.md` — one report per finding with reproduction + suggested fix
- `evidence/Q01R/B30-executor-output.json` — raw evidence
- This file — campaign summary

## Cleanup performed
- Closed all browser tabs related to the Docker instance (handled separately)
- Container `cliff-qa-rerun` and volume `cliff-qa-rerun-data` left running for follow-up; tear down with:
  ```
  docker rm -f cliff-qa-rerun
  docker volume rm cliff-qa-rerun-data
  ```
