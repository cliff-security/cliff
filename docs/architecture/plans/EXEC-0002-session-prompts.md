# EXEC-0002 — Session prompts (copy-paste ready)

**Companion to:** `EXEC-0002-from-zero-to-secure.md` (the timeline and dependencies).
**Use:** Copy the block for each session into a fresh Claude Code session. Each prompt is self-contained — no prior conversation context needed.

Every prompt assumes:

- The session is running Claude Code with full tool access (Read/Write/Edit/Bash/Task).
- The repo is checked out at `/Users/galankonina/projects/Cliff` (or the equivalent on the machine running the session).
- Session 0 has been run and merged before any of Sessions A–F start.

---

## Session 0 — Contracts freeze

**Run first. One session. Merge before spawning the parallel wave.**

> You are implementing Session 0 of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. Your job is to ship the contracts-freeze PR that unblocks every other session.
>
> **Read first, in this order:**
> 1. `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md` — the full execution plan. Your scope is "Session 0 · Contract freeze."
> 2. `docs/architecture/plans/IMPL-0002-earn-the-badge.md` — the implementation plan you are freezing the contracts for.
> 3. `docs/product/prds/PRD-0002-earn-the-badge.md` — the product spec.
> 4. `CLAUDE.md` — project conventions.
>
> **Branch:** `feat/from-zero-to-secure-contracts`
>
> **Deliverables (all in this one PR):**
>
> 1. DB migration at `backend/cliff/db/migrations/0014_from_zero_to_secure.sql`. Adds `plain_description TEXT NULL` to `findings`. Creates three new tables per IMPL-0002 Milestone A: `assessments`, `posture_checks`, `completions` (including `share_actions_used TEXT[]`).
> 2. Pydantic models for the four affected entities at `backend/cliff/models/{finding,assessment,posture_check,completion}.py`. Fields only — no DAO logic yet.
> 3. FastAPI route stubs at `backend/cliff/api/routes/{onboarding,assessment,dashboard,posture,completion}.py`. Correct request/response types, bodies raise `NotImplementedError()`. Snapshot test at `tests/api/test_openapi_snapshot.py` that freezes the current OpenAPI schema.
> 4. Auto-generate TypeScript types: run `npx openapi-typescript` against the running backend stubs and commit the output to `frontend/src/api/types.ts`.
> 5. V1↔V2 interface stub in `backend/cliff/workspace/dir_manager.py`: add `WorkspaceKind` enum with `repo_action_security_md` and `repo_action_dependabot`. Add `create_repo_workspace(kind, repo_url, params)` signature with `raise NotImplementedError`.
> 6. Five placeholder components in Storybook: `CompletionProgressCard`, `CompletionStatusCard`, `ScorecardInfoLine`, `ShareableSummaryCard`, `SummaryActionPanel`. Each renders its prop list — no styling beyond baseline.
>
> **Rules:**
>
> - TDD-first where it makes sense. The OpenAPI snapshot test must exist before the route stubs; the migration test (`tests/test_migrations.py::test_0014_schema_matches_expected`) must exist before the migration SQL.
> - Do NOT implement any real logic. Every route and every DAO and every component is a stub. This is a contracts-only PR.
> - Conventional commit messages. `feat:` for new files, `chore:` for scaffolding.
> - Open a PR to `main`. Tag `@galanko`.
>
> **Done when:** `uv run pytest -v` passes (the new tests should all pass trivially against stubs), `uv run ruff check` is clean, `npm run build` in `frontend/` succeeds, and a PR is open against `main`.

---

## Session A — Assessment engine

> You are implementing Session A of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has already merged — pull `main` first.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestone B), `docs/adr/0025-assessment-engine-and-badge-lifecycle.md`, `CLAUDE.md`.
>
> **Scope:** IMPL-0002 Milestone B (B1–B6) — lockfile parsers, OSV.dev client, GHSA fallback, posture checks, assessment orchestrator.
>
> **Owns files:** `backend/cliff/assessment/**`, fixtures under `backend/tests/fixtures/lockfiles/**`, tests under `backend/tests/assessment/**`.
>
> **Do NOT touch:** API routes (Session B), frontend (Sessions D/E/F), agent templates (Session C), DB migrations (Session 0 owns).
>
> **Uses from Session 0:** `Finding` / `Assessment` / `PostureCheck` Pydantic models. Import them, don't redefine.
>
> **TDD order:**
> 1. Check real `package-lock.json` v1, v2, v3 fixtures into `backend/tests/fixtures/lockfiles/npm/`. Write `test_npm_parser_extracts_every_dep_with_version`. Watch it fail. Write the npm parser. (B1)
> 2. Same pattern for pip (B2) and go (B3).
> 3. Write `test_osv_lookup_returns_advisories_for_braces_3_0_2` with a recorded response via `httpx.MockTransport`. Write the OSV client + GHSA fallback. (B4)
> 4. Write `test_branch_protection_check_reports_missing_rule_as_fail` with a mocked `GithubClient`. Write the posture checks module. (B5)
> 5. End-to-end unit test of the orchestrator against a fixture repo with planted vulns + planted posture issues. Write `engine.py`. (B6)
>
> **Branch:** `feat/from-zero-to-secure-assessment-engine`. One PR to `main` when all milestone-B tests pass.
>
> **Time estimate:** 3–4 hours. This is the largest backend slice.

---

## Session B — API routes + DAOs

> You are implementing Session B of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has merged — pull `main`.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestones A2, C2, D1–D5), `CLAUDE.md`.
>
> **Scope:** A2 (DAOs), C2 (thread `plain_description` through ingest), D1–D5 (five API routes with real implementations).
>
> **Owns files:** `backend/cliff/db/dao/{assessment,posture_check,completion}.py`, `backend/cliff/api/routes/{onboarding,assessment,dashboard,posture,completion}.py`, `backend/cliff/ingest/worker.py`.
>
> **Do NOT touch:** the assessment engine internals (Session A owns `backend/cliff/assessment/**`), frontend, agent templates.
>
> **Mocks you'll use:**
>
> - For the assessment engine: write a local `FakeAssessmentEngine` test double that returns a canned `AssessmentResult` matching the shape Session A will return. Your route tests wire this fake in via dependency injection. The real swap happens in Session G.
>
> **TDD order:**
> 1. Snapshot test on OpenAPI schema — should already pass from Session 0. Confirm it.
> 2. DAO tests (insert/select/upsert) per table → DAO implementations.
> 3. Route-by-route: tests first (happy path + error cases), then route body. Use the fake engine for D2.
> 4. Ingest worker: unit test that when the normalizer returns a `plain_description`, it lands in `findings.plain_description`.
>
> **Branch:** `feat/from-zero-to-secure-api-routes`.
>
> **Time estimate:** 2.5 hours.

---

## Session C — V1 agents + normalizer

> You are implementing Session C of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has merged — pull `main`.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestones C1, E1, E2, E4), `docs/adr/0022-*.md` for normalizer context, `docs/adr/0024-*.md` for the single-shot agent pattern, `CLAUDE.md`.
>
> **Scope:** extend the `finding-normalizer` agent to emit `plain_description`; create two new single-shot template agents (SECURITY.md generator, dependabot.yml generator); wire `WorkspaceKind` enum through to the process pool.
>
> **Owns files:** `.opencode/agents/finding-normalizer.md`, `backend/cliff/agents/templates/{security_md_generator,dependabot_config_generator}.md.j2`, `backend/cliff/workspace/dir_manager.py` (add enum handling), `backend/cliff/engine/pool.py` (cleanup trigger), `backend/tests/e2e/test_repo_workspace_agents.py`.
>
> **Do NOT touch:** the assessment engine, API routes, any frontend.
>
> **Do NOT create** a badge-installer agent. Badge installation is deferred to v1.2.
>
> **TDD order:**
> 1. Build the evaluation fixture at `backend/tests/agents/fixtures/plain_description_evals.json` — 10 known CVEs + expected plain-language shape assertions (presence of fix hint, no jargon allowlist). Run the eval against the current normalizer prompt, watch the shape assertions fail, then edit the prompt until they pass.
> 2. Write `test_security_md_generator_renders_template` against a fixture repo. Write the Jinja template. Then E2E test (marked `@pytest.mark.e2e`) that spawns a real repo workspace and verifies a PR is opened.
> 3. Same pattern for dependabot.
> 4. `WorkspaceKind` enum + discriminator wiring with unit tests.
>
> **Branch:** `feat/from-zero-to-secure-v1-agents`.
>
> **Time estimate:** 2.5 hours. The eval fixture work is the long tail.

---

## Session D — Frontend onboarding

> You are implementing Session D of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has merged — pull `main`.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestone F), `docs/design/specs/UX-0002-earn-the-badge.md` (Story 1 frames 1.0–1.5), `frontend/mockups/html/earn-the-badge-gallery.html` (frames 1.0–1.5, 1.1a), `CLAUDE.md` (Serene Sentinel design system).
>
> **Scope:** IMPL-0002 Milestone F (F1–F5) — the 3-step onboarding wizard, `TokenHowToDialog`, `OnboardingShell`.
>
> **Owns files:** `frontend/src/pages/onboarding/**`, `frontend/src/components/onboarding/**`, `frontend/src/components/completion/TokenHowToDialog.tsx`, `frontend/src/api/onboarding.ts` (the thin fetch wrapper).
>
> **Do NOT touch:** `DashboardPage`, completion-ceremony components (Session F), any backend file.
>
> **Mocks:** use MSW. Handlers for `POST /api/onboarding/repo` and `POST /api/onboarding/complete` live in `frontend/src/test/msw/onboardingHandlers.ts`. Tests run against MSW; dev mode also uses MSW until Session B merges (then flip to real backend — the integration step is Session G).
>
> **Design-system rules (non-negotiable):** no `1px solid` borders, tonal layering via Level 0/1/2 tokens, sentence case everywhere, `on-surface` for text, Manrope for headlines and Inter for body, Material Symbols Outlined icons only. Every new interactive element must have `focus-visible:ring-2 ring-primary/40 ring-offset-2`. See `CLAUDE.md`.
>
> **TDD order:**
> 1. Playwright component test of the happy path (welcome → verify → ai → start) against MSW mocks. Watch it fail.
> 2. Build `OnboardingShell` + `StepProgress` components. Storybook stories for each state.
> 3. Build each page (Welcome → ConnectRepo → ConfigureAI → StartAssessment) in order. Match the mockup frames pixel-for-pixel at the component level.
> 4. `TokenHowToDialog` with scrim + blur backdrop per UX spec 1.1a.
>
> **Branch:** `feat/from-zero-to-secure-fe-onboarding`.
>
> **Time estimate:** 3 hours.

---

## Session E — Frontend dashboard + findings

> You are implementing Session E of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has merged — pull `main`.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestone G), `docs/design/specs/UX-0002-earn-the-badge.md` (Stories 2, 3, 4), `frontend/mockups/html/earn-the-badge-gallery.html` (frames 2.1, 2.2, 3.1, 3.2, 4.1), `CLAUDE.md`.
>
> **Scope:** IMPL-0002 Milestone G (G1–G5) — `AssessmentProgressList`, `DashboardPage` with `CompletionProgressCard` + `ScorecardInfoLine`, `FindingRow` + `FindingDetailPage` updates, `PostureCheckItem`, `GradeRing`, `CriteriaMeter`.
>
> **Owns files:** `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/FindingDetailPage.tsx`, `frontend/src/components/dashboard/**`, `frontend/src/components/FindingRow.tsx`, `frontend/src/components/TechnicalDetailsPanel.tsx`, `frontend/src/api/dashboard.ts`.
>
> **Do NOT touch:** onboarding (Session D), completion-ceremony components (Session F), any backend. Do NOT create a `FreshnessCard` — it was cut in UX Rev 4.
>
> **Import from Session F:** `CompletionStatusCard` (the aside card that replaces the old freshness card). Session 0 shipped it as a type-only placeholder at `frontend/src/components/completion/CompletionStatusCard.tsx` — you import the stub, Session F builds the real internals.
>
> **Mocks:** extend `frontend/src/test/msw/server.ts` (scaffolded by Session D) with a `dashboardHandlers` module — do NOT create a parallel MSW setup. Handler for `GET /api/dashboard` returns a seeded payload covering three states: assessment-running, grade-C-with-issues, grade-A-completion-holding.
>
> **Design-system rules:** same as Session D. Non-negotiable.
>
> **Tooling note (updated from Session D):** Session 0 did not scaffold Storybook; Session D used vitest + RTL instead. Match that — colocate component tests under `__tests__/` and skip Storybook for v1.1. If you want Storybook, it's a follow-up PR.
>
> **TDD order:**
> 1. Vitest+RTL happy-path test for `DashboardPage` against the seeded MSW fixture. Watch it fail.
> 2. `CompletionProgressCard` (component + test) in the "3 of 5 met" state.
> 3. `ScorecardInfoLine`. External link MUST have `target="_blank" rel="noopener noreferrer"`.
> 4. `GradeRing`, `CriteriaMeter`.
> 5. `DashboardPage` layout wiring the above + `CompletionStatusCard` import (stub) + vulns card + posture card.
> 6. `AssessmentProgressList` consuming the SSE status endpoint.
> 7. `FindingRow` + `FindingDetailPage` + `PostureCheckItem` updates.
>
> **Copy rule:** any user-visible string referencing "badge" must say "completion" instead, except in the Scorecard info line (which may reference external security badges generically). "Needed for badge" → "Needed for completion". "Earn the badge" → "Reach security completion". Full vocabulary in UX spec.
>
> **Branch:** `feat/from-zero-to-secure-fe-dashboard`.
>
> **Time estimate:** 3.5 hours.

---

## Session F — Frontend completion ceremony + summary card

> You are implementing Session F of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. The contracts freeze (Session 0) has merged — pull `main`.
>
> **Read first:** `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestone H), `docs/design/specs/UX-0002-earn-the-badge.md` (Story 5 and the Sanctioned exceptions subsection of Design system compliance), `frontend/mockups/html/earn-the-badge-gallery.html` (frames 5.1 and 5.2), `CLAUDE.md`.
>
> **Scope:** IMPL-0002 Milestone H (H1–H5) — `ShieldSVG`, `CompletionCelebration`, `ConfettiLayer`, `ShareableSummaryCard`, `SummaryActionPanel`, `CompletionStatusCard`, `imageExport.ts`.
>
> **Owns files:** `frontend/src/components/completion/**` (except `TokenHowToDialog.tsx` which Session D owns), `frontend/src/lib/imageExport.ts`, `frontend/package.json` (add `html-to-image`).
>
> **Do NOT touch:** onboarding, dashboard page body. The dashboard imports `CompletionStatusCard` from your tree — that is the contract.
>
> **Do NOT create** an `AddBadgeDialog`, a `FreshnessCard`, or any "Add badge to README" PR flow. All deferred to v1.2.
>
> **Design rules that are specific to this session:**
>
> - `ShareableSummaryCard` uses the **sanctioned gradient exception**: `linear-gradient(135deg, #4d44e3 0%, #575e78 100%)`. This is the only surface in the product that uses a gradient. Do not replicate this gradient anywhere else.
> - All white text on the gradient MUST use `rgba(255,255,255,0.92)` minimum. Verify via a React-Testing-Library test that greps the rendered inline styles.
> - `CompletionStatusCard` shield is a real `<button type="button">` with `aria-label="Re-open shareable summary card"`, `focus-visible:ring-2 ring-primary/40`, `hover:scale-105 transition-transform`. A "Tap for summary" micro-label fades in on hover (opacity 0→100).
> - Three share-action tiles on `SummaryActionPanel` all follow the same shape: header (icon + title + one-line description) → preview block → action button. Download tile's preview block is a metadata row (`image` icon + filename + dimensions + size).
>
> **Share-action recording:** every click on Download / Copy text / Copy markdown MUST call `POST /api/completion/{id}/share-action` fire-and-forget with the correct action string. Debounce double-clicks so one click = one POST.
>
> **PNG export:** `imageExport.ts` uses `html-to-image`'s `toPng` with `{ pixelRatio: 2, cacheBust: true, width: 1200, height: 630 }`. Dynamic import the library only when the user clicks Download so it doesn't inflate first-paint bundle. Cross-browser Playwright smoke (Chromium, Firefox, WebKit) runs in Session G — you just need the jsdom unit test.
>
> **Mocks:** extend `frontend/src/test/msw/server.ts` (scaffolded by Session D) with a `completionHandlers` module. Handler for `POST /api/completion/:id/share-action` returns 204.
>
> **Tooling note (updated from Session D):** Session 0 did not scaffold Storybook; Session D used vitest + RTL instead. Match that — colocate component tests under `__tests__/` and skip Storybook for v1.1. `TokenHowToDialog` already lives at `frontend/src/components/completion/TokenHowToDialog.tsx` — do not touch it.
>
> **TDD order:**
> 1. React-Testing-Library test of `ShareableSummaryCard` asserting all six props render and the `rgba` contrast values appear in the rendered inline styles. Build the component.
> 2. `ShieldSVG` — vitest snapshot at three sizes.
> 3. `CompletionCelebration` overlay with `ConfettiLayer`. Assert `role="status" aria-live="assertive"`. Respect `prefers-reduced-motion`.
> 4. `SummaryActionPanel` three tiles. Test click-through wiring to MSW.
> 5. `imageExport.ts` with jsdom test asserting the library is called with the right options. Dynamic-import under the hood.
> 6. `CompletionStatusCard` with the shield-as-button affordance. Test keyboard activation (`Enter` and `Space`).
>
> **Branch:** `feat/from-zero-to-secure-fe-completion`.
>
> **Time estimate:** 3 hours.

---

## Session G — Integration + E2E

**Run last. After Sessions A–F have all merged.**

> You are implementing Session G of `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`. Sessions A–F have merged to `main` — pull the latest.
>
> **Read first:** `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md` (Session G block), `docs/architecture/plans/IMPL-0002-earn-the-badge.md` (Milestone I), and **`docs/known-issues/session-b-handoff-gaps.md`** — three inter-session contract gaps that Session B's merged code assumes Session A resolves in a specific way. Validate each before declaring integration done.
>
> **Scope:** integration, E2E, cross-browser smoke, contributor docs. The feature flag flip.
>
> **Steps:**
>
> 1. Delete the MSW mocks in the frontend for routes that now have real backend implementations. Routes: `POST /api/onboarding/repo`, `POST /api/onboarding/complete`, `POST /api/assessment/run`, `GET /api/assessment/status/:id`, `GET /api/assessment/latest`, `GET /api/dashboard`, `POST /api/posture/fix/:check`, `POST /api/completion/:id/share-action`. Leave any others mocked if they exist. Specifically: strip `startMockApi()` from `frontend/src/main.tsx` (or flip its default so the `VITE_USE_REAL_API` gate becomes the fall-through), remove `frontend/src/test/msw/browser.ts`, and delete `frontend/public/mockServiceWorker.js`. The Vitest server at `frontend/src/test/msw/server.ts` stays for unit-test isolation.
> 2. Wire the real engine into the DI seam. Edit `backend/cliff/api/_engine_dep.py::get_assessment_engine` so its body returns Session A's engine (`from cliff.assessment.engine import AssessmentEngine; return AssessmentEngine(...)`). Same for `get_repo_workspace_spawner` — its body should construct and return the spawner shim built on top of Session C's `WorkspaceDirManager.create_repo_workspace`. Do NOT touch the protocol definitions or route code; the DI seam is designed so integration is a two-line body swap. Then resolve the three contract gaps in `docs/known-issues/session-b-handoff-gaps.md` (posture-check dict shape, findings persistence path, DAO-write ownership) — each is either a "Session A already did it this way, good" confirmation or a small adapter in `_background.run_and_persist_assessment`. Re-run `uv run pytest -v` — route tests still use `app.dependency_overrides` with the fake and must stay green.
> 3. **Contract gap from Session D — close it here.** The `OnboardingRepoResponse` Session-0 stub is `{ assessment_id, repo_url }`. Session D's `ConnectionResultCard` reads `response.verified` (visibility, default branch, permissions) from the MSW payload. Either (a) extend `backend/cliff/api/routes/onboarding.py::OnboardingRepoResponse` to return a `verified: VerifiedRepoSummary` subobject populated by Session B's real repo check, or (b) make `ConnectionResultCard` render a derived-from-URL fallback when `verified` is absent. Prefer (a) — it's two fields and the backend already hits the GitHub API. Update `frontend/src/api/types.ts` via `npm run generate:types`.
> 4. In `backend/tests/api/`, replace the `FakeAssessmentEngine` from Session B with the real engine from Session A (the route DI override; the production wiring is step 2). Re-run the full backend test suite — `uv run pytest -v`. Fix any integration breakage by reopening the owning session's PR as a hot-fix.
> 5. Write the end-to-end Playwright test at `frontend/tests/e2e/from_zero_to_secure.spec.ts`: start from empty DB, complete onboarding against a seeded fixture repo, run assessment, solve one finding, reach completion, click Download, verify a non-empty PNG lands in the Playwright download directory. Verify via backend check that `completions.share_actions_used` contains `download`.
> 6. Run the cross-browser PNG-export smoke across Chromium, Firefox, and WebKit (`playwright test --project=chromium --project=firefox --project=webkit`). Note: Session D and Session F shipped without Playwright CT — this is the first Playwright install in the repo. `npm install --save-dev @playwright/test` + `npx playwright install` + a minimal `playwright.config.ts` is part of this session's setup.
> 7. Write `docs/guides/assessment-engine.md` — a contributor guide for adding a new lockfile parser or posture check. 1–2 pages.
> 8. Add a `CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED` feature flag to `backend/cliff/config.py` defaulting to `false`. Guard the new onboarding-wizard redirect behind it.
> 9. Smoke-test the full flow manually against a throwaway repo. Screenshot the celebration + summary card for the PR description.
>
> **Branch:** `feat/from-zero-to-secure-integration`. This is the final PR.
>
> **Done when:** all tests green, all three browsers pass the PNG smoke, manual smoke is clean, PR is open with screenshots. `@galanko` merges and decides when to flip the flag on.
>
> **Time estimate:** 90–120 minutes.

---

## Quick reference: branch cheat sheet

| Session | Branch |
|---|---|
| 0 | `feat/from-zero-to-secure-contracts` |
| A | `feat/from-zero-to-secure-assessment-engine` |
| B | `feat/from-zero-to-secure-api-routes` |
| C | `feat/from-zero-to-secure-v1-agents` |
| D | `feat/from-zero-to-secure-fe-onboarding` |
| E | `feat/from-zero-to-secure-fe-dashboard` |
| F | `feat/from-zero-to-secure-fe-completion` |
| G | `feat/from-zero-to-secure-integration` |
