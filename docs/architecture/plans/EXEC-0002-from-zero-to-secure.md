# EXEC-0002: From zero to secure — single-day parallel execution plan

**Companion to:** `IMPL-0002-earn-the-badge.md` (the what and why)
**This doc:** the when and who — how to split IMPL-0002 across parallel Claude Code sessions so the entire PRD ships in a single working day.
**Status:** Draft — awaiting CEO approval
**Date:** 2026-04-15
**Target:** merge all PRs to `main` by end of day, behind a feature flag if needed

---

## The plan in one sentence

Freeze the contracts (DB schema, API shapes, V1↔V2 interface) in the morning as a small Session-0 sprint, then fan out six parallel Claude Code sessions against those frozen contracts, then spend the last 2 hours on a single integration session that wires them together and runs the E2E suite.

## Why this works in a day

Three properties make parallel single-day delivery possible here:

1. **Clean vertical separation.** The assessment engine, the V1 agent templates, the onboarding UI, the dashboard UI, and the completion UI each live in their own directory trees. Cross-cutting concerns are limited to the DB schema and ~6 API routes.
2. **TDD with mocked dependencies.** Each session can start from a failing test, build against a mock of what it doesn't own, and integrate later. The "do I block on the other team" question collapses to "do I have the contract I'm building against."
3. **No new architectural decisions.** IMPL-0002 and ADR-0025 already decided everything. Sessions execute, they don't re-design.

---

## Session 0 · Contract freeze (sequential, ~60 minutes, one session only)

This is the only sequential block. Do it first, with a single session, while nothing else is running. Everything after depends on these artifacts being stable.

**Owner:** one Claude Code session, ideally driven by @galanko directly or by a senior-level session that can make small judgment calls.

**Deliverables (all land in one PR to `main`):**

1. **DB migration SQL** committed as `backend/cliff/db/migrations/0014_from_zero_to_secure.sql`. Contents per IMPL-0002 Milestone A: `plain_description` column on `findings`, plus `assessments`, `posture_checks`, `completions` tables. Migration can be unapplied on dev; the file defines the shape every other session builds against.
2. **Pydantic models** for the four affected entities: `backend/cliff/models/{finding,assessment,posture_check,completion}.py`. Fields only — no DAO logic yet. These are the types every backend session imports.
3. **API route OpenAPI stubs** for every new endpoint. FastAPI `@router.post(...)` decorators with the right request/response shapes but bodies that just `raise NotImplementedError()`. Committed as stubs in `backend/cliff/api/routes/{onboarding,assessment,dashboard,posture,completion}.py`. The OpenAPI schema snapshot is committed to `tests/api/test_openapi_snapshot.py` — frozen from the first run.
4. **Frontend types** auto-generated from the OpenAPI stub via `openapi-typescript` into `frontend/src/api/types.ts`. Committed. The frontend sessions import types from here.
5. **V1↔V2 interface stub** in `backend/cliff/workspace/dir_manager.py`: the `WorkspaceKind` enum with `repo_action_security_md` and `repo_action_dependabot`, plus the `create_repo_workspace(kind, repo_url, params)` signature (body raises `NotImplementedError`).
6. **Storybook entries for the five new component names** (`CompletionProgressCard`, `CompletionStatusCard`, `ScorecardInfoLine`, `ShareableSummaryCard`, `SummaryActionPanel`) — empty placeholder components that render their prop list. Lets the frontend sessions integrate as soon as any of these become real.

**Branch:** `feat/from-zero-to-secure-contracts`. One PR. Merge this before fanning out.

**Why this matters:** without Session 0 done and merged, the parallel sessions will drift. Five sessions picking slightly different JSON shapes for "assessment status" is how you lose a day.

---

## Parallel wave · six sessions running simultaneously (~5 hours of wall time)

After Session 0 merges, start all six sessions at the same time. Each session owns a distinct slice of the code tree. Each session branches from `main` (which now has the frozen contracts) and targets its own PR.

### Session A · Assessment engine (backend, deterministic)

**Scope:** IMPL-0002 Milestone B (B1–B6) — lockfile parsers, OSV.dev client, GHSA fallback, posture checks, assessment orchestrator.
**Owns files:** `backend/cliff/assessment/**`, fixtures under `backend/tests/fixtures/lockfiles/**`, `backend/tests/assessment/**`.
**Does NOT touch:** API routes, frontend, agent templates.
**Depends on (from Session 0):** the `Finding` / `Assessment` / `PostureCheck` Pydantic models.
**Starts by writing:** `test_npm_parser_extracts_every_dep_with_version` against a checked-in `package-lock.json` fixture, watching it fail, then writing the parser.
**Branch:** `feat/from-zero-to-secure-assessment-engine`.
**Size indicator:** ~3–4 hours for one focused session. Largest backend slice.

### Session B · API routes + DAOs (backend, thin layer)

**Scope:** IMPL-0002 Milestone A (A2 — DAOs) and Milestone D (D1, D2, D3, D4, D5) — DAO functions for the three new tables + real implementations of the five new API routes.
**Owns files:** `backend/cliff/db/dao/{assessment,posture_check,completion}.py`, `backend/cliff/api/routes/{onboarding,assessment,dashboard,posture,completion}.py`, `backend/cliff/ingest/worker.py` (for C2 — threading `plain_description` through ingest).
**Does NOT touch:** assessment engine internals, frontend, agent templates.
**Depends on (from Session 0):** migration + OpenAPI stubs.
**Uses mocks for:** the assessment engine (Session A) — mock `run_assessment(repo_url)` to return a canned `AssessmentResult` and test the route in isolation. Real integration happens in Session G.
**Starts by writing:** snapshot test on the OpenAPI schema (which should already pass from Session 0), then TDD each route against the canned engine mock.
**Branch:** `feat/from-zero-to-secure-api-routes`.
**Size indicator:** ~2.5 hours.

### Session C · V1 agents + normalizer (backend, agent templates)

**Scope:** IMPL-0002 Milestone C (C1 — normalizer prompt extension) and Milestone E (E1, E2, E4) — two generator agents and the `WorkspaceKind` wiring.
**Owns files:** `.opencode/agents/finding-normalizer.md`, `backend/cliff/agents/templates/{security_md_generator,dependabot_config_generator}.md.j2`, `backend/cliff/workspace/dir_manager.py` (add enum), `backend/cliff/engine/pool.py` (cleanup trigger).
**Does NOT touch:** assessment engine, API routes, frontend.
**Depends on (from Session 0):** `WorkspaceKind` enum stub.
**Starts by writing:** evaluation fixture of 10 known CVEs with expected plain-language shapes → watch normalizer fail → edit prompt.
**Branch:** `feat/from-zero-to-secure-v1-agents`.
**Size indicator:** ~2.5 hours. LLM eval fixture work is the long tail.

### Session D · Frontend onboarding

**Scope:** IMPL-0002 Milestone F (F1–F5) — the 3-step wizard, `TokenHowToDialog`, `OnboardingShell`, welcome, connect repo, configure AI, start assessment.
**Owns files:** `frontend/src/pages/onboarding/**`, `frontend/src/components/onboarding/**`, `frontend/src/components/completion/TokenHowToDialog.tsx`.
**Does NOT touch:** dashboard page, completion components, any backend.
**Depends on (from Session 0):** `frontend/src/api/types.ts` (onboarding endpoint types), onboarding route stubs.
**Uses mocks for:** the backend — MSW (Mock Service Worker) handlers for `POST /api/onboarding/repo` and `POST /api/onboarding/complete` so the UI can be built and tested before Session B is done.
**Starts by writing:** Playwright component test of the happy path (welcome → verify → ai → start) against MSW mocks.
**Branch:** `feat/from-zero-to-secure-fe-onboarding`.
**Size indicator:** ~3 hours.

### Session E · Frontend dashboard + findings

**Scope:** IMPL-0002 Milestone G (G1–G5) — `AssessmentProgressList`, `DashboardPage` with `CompletionProgressCard` + `ScorecardInfoLine`, `FindingRow` + `FindingDetailPage` updates, `PostureCheckItem`, `GradeRing`, `CriteriaMeter`.
**Owns files:** `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/FindingDetailPage.tsx`, `frontend/src/components/dashboard/**`, `frontend/src/components/FindingRow.tsx`, `frontend/src/components/TechnicalDetailsPanel.tsx`.
**Does NOT touch:** onboarding, completion ceremony components.
**Depends on (from Session 0):** dashboard + findings API types, Storybook placeholders.
**Uses mocks for:** the dashboard API — MSW handler returning a seeded `DashboardPayload`.
**Starts by writing:** Storybook story for `CompletionProgressCard` with the three-met-two-remaining state, then the component.
**Branch:** `feat/from-zero-to-secure-fe-dashboard`.
**Size indicator:** ~3.5 hours. Most components live here.

### Session F · Frontend completion ceremony + summary card

**Scope:** IMPL-0002 Milestone H (H1–H5) — `ShieldSVG`, `CompletionCelebration`, `ConfettiLayer`, `ShareableSummaryCard`, `SummaryActionPanel`, `CompletionStatusCard`, `imageExport.ts`.
**Owns files:** `frontend/src/components/completion/**`, `frontend/src/lib/imageExport.ts`, `frontend/package.json` (add `html-to-image`).
**Does NOT touch:** onboarding, dashboard page (but DOES export components that the dashboard page imports — the contract is the component API).
**Depends on (from Session 0):** completion API types (specifically the `share-action` endpoint), Storybook placeholders for the four new components.
**Uses mocks for:** the `share-action` POST endpoint via MSW.
**Starts by writing:** React-Testing-Library test of `ShareableSummaryCard` asserting all six props render in the correct slots and that the declared `rgba(255,255,255,0.92+)` contrast values appear in the rendered inline styles. Then the component. Then `imageExport.ts` with a jsdom test. The Playwright cross-browser test (I4) runs in Session G.
**Branch:** `feat/from-zero-to-secure-fe-completion`.
**Size indicator:** ~3 hours. New visual work + PNG export is the novelty.

---

## Session G · Integration + E2E (sequential, ~90–120 minutes)

After all six parallel sessions have merged their PRs, run one final session to wire everything together and prove it works end-to-end.

**Scope:** IMPL-0002 Milestone I (I1–I4).
**Steps:**

1. Replace the MSW mocks in the frontend with real backend calls — already should "just work" if the contracts held, but confirm.
2. Replace the canned assessment mock in Session B's route tests with the real engine from Session A. Re-run all backend tests.
3. Write the Playwright E2E spec: onboarding → assessment → solve one finding → reach completion → download summary image → verify PNG lands on disk → verify `share_actions_used` row contains `download`.
4. Run the Playwright cross-browser smoke (Chromium, Firefox, WebKit) for the image export.
5. Update `docs/guides/` with the "Assessment engine" contributor guide (I2).
6. If any integration breakage surfaced, assign a fix to the owning session's original author (in a rapid hot-fix PR) and re-run.

**Branch:** `feat/from-zero-to-secure-integration`.
**This PR also flips the feature flag on** — or leaves it off for a canary period, per your call.

---

## Dependency map at a glance

```
Session 0 (contracts) ─┬─▶ Session A (assessment engine)       ──┐
                       ├─▶ Session B (API routes + DAOs)        ─┤
                       ├─▶ Session C (V1 agents + normalizer)   ─┼─▶ Session G (integration + E2E) ─▶ merge
                       ├─▶ Session D (frontend onboarding)      ─┤
                       ├─▶ Session E (frontend dashboard)       ─┤
                       └─▶ Session F (frontend completion)      ─┘
```

No arrow between A/B/C/D/E/F. They do not block each other *because* each uses mocks for what it doesn't own, and the contracts from Session 0 are stable.

## Timeline (if you start at 9am)

| Time | What's happening |
|---|---|
| 09:00–10:00 | **Session 0** runs solo. Contracts ship to `main`. |
| 10:00–14:30 | **Sessions A–F** run in parallel. Each produces a PR against `main`. Architect reviews each PR as it lands (can happen with `/architect` on a short leash). |
| 14:30–15:00 | Buffer for last PR to land + architect catch-up. |
| 15:00–17:00 | **Session G** — integration, E2E, cross-browser smoke, docs. Final PR. |
| 17:00 | Feature flag flip (or ship off by default for canary). Done. |

Total wall-clock time: ~8 hours including buffer. Actual compute across all sessions: ~18 hours of session-hours compressed into 6 hours of parallel execution.

## How to run the parallel wave in practice

For each of Sessions A–F:

1. **Spawn the session with a self-contained prompt** — include:
   - The session's scope block from this doc, verbatim
   - A link to IMPL-0002 and to `CLAUDE.md`
   - The session's branch name
   - Explicit instruction: "Do NOT modify files outside your `Owns files` list. If you need to, stop and ask."
2. **Require TDD-first** — the prompt should insist that the failing test is committed before the implementation.
3. **Each session opens its own PR against `main`** — no chain PRs, no stacked branches. If Session B needs something from Session A that's not in the contract, the fix goes into Session 0's contract PR as a hot amendment, not a branch-to-branch dependency.
4. **Architect review per PR.** You (or `/architect`) review each one as it lands, not all-at-once at the end. A 5-minute review per PR keeps the wave moving.
5. **Run your own CI on every PR.** Lint + unit tests gate merge. E2E waits for Session G.

## What to do if a session blows through its estimate

Two escape valves:

- **Cut scope to P1/P2.** Every session has a P0 core and nice-to-have polish. If Session E is running long, drop the Storybook snapshots and ship component behavior only — add snapshots in a follow-up PR.
- **Defer non-P0 acceptance criteria.** PRD success metrics like "3+ friends say they'd recommend" are user-study tasks, not code tasks. Not shipping those today is fine.

If two or more sessions blow through their estimate, the right call is to split the remaining work into a "v1.1a" follow-up PR and ship v1.1 core by end of day. Better to ship the assessment + completion ceremony without the shareable summary card than to slip the whole PRD.

## Rollback plan

If anything ships broken:

- The feature is behind a flag `CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED` defaulting to `false`. Flip off.
- Database migration `0014` is additive only — no existing column is dropped or renamed. Safe to leave applied even if the feature is off.
- V1 agents (security_md, dependabot) are new templates — their absence doesn't affect existing finding workspaces.
- Frontend routes guard the onboarding wizard behind `onboarding_completed === false`; if the flag is off, the wizard is never shown.

No rollback migration is needed. Worst-case: feature flag off, main is stable.

## What this plan is NOT

- **Not a license to skip TDD.** Single-day velocity works because the tests are the contract. Skip tests and integration day becomes integration week.
- **Not a license to skip architect review.** Every PR still goes through `/architect` before merge. The gains come from parallelism, not from dropping quality gates.
- **Not a license to lump milestones.** Each session ships its own PR. "One mega-PR at the end of the day" is the anti-pattern this plan exists to prevent.

---

## Handoff

Once CEO approves this execution plan:

1. Start Session 0 immediately. Merge the contracts PR.
2. Spawn Sessions A–F in parallel with prompts derived from this doc's session blocks.
3. Keep `/architect` on standby for rapid review turnaround.
4. At ~14:30, collect status from all six sessions. Green-light Session G.
5. End of day: flag flip or canary decision.

If any session returns with "blocked — need X from another session," that's a Session-0 miss. Treat it as a hot fix to Session 0's contracts PR, not as a cross-session blocker.
