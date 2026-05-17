# QA-0001 / Q01 re-run (Wave 1.5) — UI-only on fresh Docker

**Date**: 2026-05-17
**Driver**: Claude in Chrome — UI only, `opensec` CLI forbidden per Wave 2 policy
**Target**: cliff-security/NodeGoat (master branch)
**Environment**:
- Docker image `opensec:qa-rerun` built from `main` at commit `6d2d228`
- Container on port 8088, fresh volume `opensec-qa-rerun-data`, fresh credential key
- No provider env vars (forces real BYOK flow)
- Provider: OpenRouter OAuth → `openrouter/anthropic/claude-haiku-4.5` (auto-selected)
- GitHub: galanko, device-flow OAuth (`opensec-local-test` app, installation_id=133122855)

## Headline verdict: RED

Two P0 bugs in series prevent any UI-only user from producing a real remediation PR on this build:

- **B29** — no UI affordance to approve the plan or trigger the executor. Plan completes, user has no way forward.
- **B30** — even when the executor is triggered (via curl bypass), it can't push because the GitHub App OAuth user token lacks `contents:write` on the org repo.

Either alone is a release blocker. Together they sink the entire happy-path narrative for the UI-only configuration that Wave 2 is mandating.

## Wave-1 fixes verified at runtime

| Wave-1 bug | Verified now? | How |
|---|---|---|
| **B02** readiness gate lying | ✓ fixed | `/health` returns `ai_provider_ready:false` until OAuth completes, then flips to true. Default-model fallback (`gpt-4.1-nano`) shows before BYOK and switches to the OAuth-selected model after. |
| **B06** BYOK propagation | ✓ fixed | OpenRouter OAuth-flow key reaches subprocess; model auto-selects to `claude-haiku-4.5`. |
| **B08** hallucination tripwires | ✓ (sample) | Enricher output for the minimist Critical was clean: real CVE-2021-44906, real fixed-version 1.2.6, real CWE/NVD URLs. No Cyrillic-corrupted SHAs or fabricated GHSAs. |
| **B14** hollow close | ✗ regressed (different cause) | Executor `"completed"` but `pr_url` stayed null. This time the root cause is B30 (push denied) rather than reconcile-on-close — but the user-visible symptom is identical: a "done" finding with no PR. |
| **B17** 76s timeout under concurrency | ✓ effective | Single-finding plan stage completed in ~60s with no timeouts; pool=3 left room. |

## New defects (B22–B30)

| ID | Sev | Title | Surface |
|---|---|---|---|
| B22 | P1 | OAuth UI stays "Waiting for you to authorize" after callback succeeds | UI |
| B23 | P1 | Posture checks hit `branches/main` and `commits?sha=main` (404/403 on master-default repos) | backend |
| B24 | P0 | Auto-fix posture: frontend offers checks backend rejects (422); UI swallows the error silently | UI + backend |
| B25 | P2 | `/issues?severity=critical` URL param ignored on initial render | UI |
| B26 | P3 | "Review is clear" + green check shown when 45 issues are queued | UI |
| B27 | P2 | Dashboard "Start" cards navigate to filter view instead of driving the work | UI |
| B28 | P1 | Workspace side-panel "Thinking…" widget stays stale after agents complete | UI |
| **B29** | **P0** | **No UI affordance to approve the plan / trigger executor** | **UI** |
| **B30** | **P0** | **Executor push fails — GitHub App OAuth token lacks write scope on org repo** | **backend + App config** |

Per-bug reports with reproduction + suggested fix live in `evidence/Q01R/B22-*.md` through `B30-*.md`. Raw evidence (executor run record) in `evidence/Q01R/B30-executor-output.json`.

P0 + P1 cluster all in UI/UX layer except B23 + B30 — the engine itself is sound for the parts that ran.

## What worked (keep these)

- Onboarding flow (welcome → connect → AI → assess) is 3 clear screens, ~3 min as promised.
- Repo picker is clean; GH device flow works; callback hits the Docker container correctly.
- OpenRouter OAuth in Docker (port 3000 callback) works end-to-end — validates the recent fix (973d055).
- Assessment runs automatically from onboarding; dashboard appears with grade.
- Dashboard "Level up to D" panel is excellent — gives concrete actionable next steps and the grading rubric is transparent ("Steady at F. Two more closures away from D.").
- Plan-stage agent quality is high: 95% confidence on the right CVE, right fixed version, right files.
- Activity log inside the side panel renders each agent run with confidence, duration, and summary.

## What to fix before Wave 2 runs

Priority order:

1. **B29 + B30** — Wave 2 cannot run a UI-only campaign at all until these land.
2. **B24** — first thing a new user clicks is broken; fix the autofix contract and surface 4xx errors.
3. **B22 + B28** — fix the polling pattern across the app; the same root cause shows up in three places (OAuth, plan stage, executor stage).
4. **B23** — branch-name detection broken for any non-`main` default; trivial fix, prevents falsely-failing posture checks on older repos.
5. **B25, B26, B27** — UX polish, but B27 in particular hurts because it's the first interaction after onboarding.

## Wave 2 prerequisites (campaign-wide)

Adapted from the user's instructions during this session, to be enforced by the campaign prompt the cowork session will rewrite:

- Every campaign run must start from branch `qa/q01-campaign-fixes` (no testing on stale main).
- Every campaign run deploys a fresh Cliff container (fresh DB, fresh credential key, no inherited provider env vars).
- Every prompt explicitly lists the flow: build → launch → onboarding (UI) → finding triage (UI) → re-assessment (UI) → cleanup.
- After report + bug investigations are done, every session tears down its own container and volume.
- Concurrency is improved — the campaign drives multiple findings in parallel with explicit pool sizing.
- For every user role except the opensec-CLI QA session, the work is driven entirely via Claude-in-Chrome against the Cliff UI. CLI use is forbidden.
- Every session pursues grade A on the dashboard and follows the dashboard's own "Level up to" guidance. If a dashboard instruction is unclear, that itself is a bug to file.

## Files

- `docs/qa/QA-0001-Q01R-rerun-ui-only.md` — this file (campaign summary)
- `docs/qa/evidence/Q01R/SUMMARY.md` — long-form summary
- `docs/qa/evidence/Q01R/B22-*.md` through `B30-*.md` — per-bug reports
- `docs/qa/evidence/Q01R/B30-executor-output.json` — raw evidence

## Cleanup

Container `opensec-qa-rerun` and volume `opensec-qa-rerun-data` left running for follow-up investigation. Tear down with:

```
docker rm -f opensec-qa-rerun
docker volume rm opensec-qa-rerun-data
```
