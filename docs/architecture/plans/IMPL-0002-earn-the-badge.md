# IMPL-0002: From zero to secure

**PRD:** `docs/product/prds/PRD-0002-earn-the-badge.md`
**UX Spec:** `docs/design/specs/UX-0002-earn-the-badge.md`
**ADR:** `docs/adr/0025-assessment-engine-and-badge-lifecycle.md` *(needs a minor revision pass — see note at bottom)*
**Status:** Revised 2026-04-15 — awaiting CEO review
**Date:** 2026-04-14 (original) / 2026-04-15 (revision 2)
**Architect:** architect skill

---

## Revision note (2026-04-15)

PRD-0002 was scoped down on 2026-04-15. The public "Secured by Cliff" README PR and the live OpenSSF Scorecard integration were both deferred to v1.2. v1.1 now ships an in-app completion ceremony plus a **user-controlled, locally-rendered shareable summary card** (PNG generated client-side, three user-initiated actions: download, copy text, copy markdown). UX-0002 Revision 4 followed with design-critique fixes.

Changes from IMPL-0002 Revision 1:

- **Dropped work:** badge-installer agent (E3), `POST /api/badge/add-to-readme` route (part of D3), `AddBadgeDialog` component, `FreshnessCard` component, badge-verification-URL semantics on the shield SVG.
- **Renamed work:** `BadgePreviewCard` → `CompletionProgressCard`; `BadgeEarnedCelebration` → `CompletionCelebration`. Same component, new label — no behavior change.
- **New work:** `ShareableSummaryCard` component (a renderable 1200×630 React component that also exports itself as PNG via `html-to-image`), `SummaryActionPanel` (three action tiles), `CompletionStatusCard` (dashboard aside replacing the freshness card), `ScorecardInfoLine` (static info sentence), completion-events audit table (previously `badges` table, renamed to `completions` and semantically simpler).
- **Unchanged work:** onboarding wizard, assessment engine, lockfile parsers, OSV/GHSA clients, posture checks, plain-language descriptions, SECURITY.md and dependabot.yml generator agents, all findings UI, all dashboard UI below the aside.

Net scope change: **−1 agent, −1 API route, −2 components; +4 components, +0 API routes, +0 agents.** Approximately net-neutral on code volume, net-positive on trust posture.

---

## Summary

Build the onboarding → assessment → plain-language findings → posture guidance → completion ceremony flow described in PRD-0002 (revised). The chosen shape:

- **Assessment engine** is deterministic Python in a new `backend/cliff/assessment/` module. No LLM calls during the mechanical parts; the existing `finding-normalizer` agent is extended to emit plain-language descriptions on the way through. **Unchanged from Revision 1.**
- **Completion state is derived** from findings + latest posture results at read-time. We persist two event-level tables (`assessments`, `posture_checks`) and one audit/ceremony table (`completions`) — no `is_complete` flag anywhere. **Renamed `badges` → `completions`.**
- **Two PR actions** (SECURITY.md, dependabot.yml) reuse the existing ephemeral-workspace + single-shot-template-agent pattern (ADR-0024). One new "repo workspace" kind distinguishes them from finding workspaces. **Was three actions, now two.**
- **Shareable summary card is rendered client-side.** The `ShareableSummaryCard` React component renders a 1200×630 deterministic DOM layout (indigo→slate gradient, repo name, stats, grade). The Download action converts that DOM to PNG via `html-to-image` in the browser and triggers a save dialog. No server involvement, no hosted URL, no account. **New in Revision 2.**
- **Three lockfile parsers ship in IMPL-0002** (npm, pip, go). The remaining five ship as follow-up PRs with no schema change. **Unchanged from Revision 1.**

## Team assignments

### V2 — App Builder (owns ~82% of this plan, up slightly from 80% because the ceremony + summary card work is all frontend)

| Area | Files |
|---|---|
| Assessment engine | `backend/cliff/assessment/**` (new module) |
| DB schema | `backend/cliff/db/migrations/0014_from_zero_to_secure.sql` — add `plain_description` column, three new tables (`assessments`, `posture_checks`, `completions`) |
| API routes | `backend/cliff/api/routes/{onboarding,assessment,dashboard,posture,completion}.py` — **no `badge.py`** |
| Model updates | `backend/cliff/models/finding.py` (add `plain_description`) |
| Frontend — onboarding | `frontend/src/pages/onboarding/{Welcome,ConnectRepo,ConfigureAI,StartAssessment}.tsx`, `frontend/src/components/onboarding/**` |
| Frontend — dashboard | `frontend/src/pages/DashboardPage.tsx`, `frontend/src/components/dashboard/{GradeRing,CompletionProgressCard,CriteriaMeter,CompletionStatusCard,ScorecardInfoLine,AssessmentProgressList,PostureCheckItem,AssessmentDiffList}.tsx` |
| Frontend — finding updates | `frontend/src/components/FindingRow.tsx`, `frontend/src/pages/FindingDetailPage.tsx`, `frontend/src/components/TechnicalDetailsPanel.tsx` |
| Frontend — completion ceremony | `frontend/src/components/completion/{ShieldSVG,CompletionCelebration,ConfettiLayer,ShareableSummaryCard,SummaryActionPanel,TokenHowToDialog}.tsx` |
| Frontend — PNG export | Add `html-to-image` dep. Thin wrapper in `frontend/src/lib/imageExport.ts` that takes a DOM ref and returns a PNG blob |

### V1 — Agent Orchestrator

| Area | Files |
|---|---|
| Normalizer prompt extension | `.opencode/agents/finding-normalizer.md` (extend output contract with `plain_description`), `backend/cliff/agents/templates/finding_normalizer.md.j2` if template-driven |
| SECURITY.md generator agent | `backend/cliff/agents/templates/security_md_generator.md.j2` (new) |
| Dependabot config generator agent | `backend/cliff/agents/templates/dependabot_config_generator.md.j2` (new) |
| ~~Badge installer agent~~ | **Removed.** Deferred to v1.2 when the public README badge returns |
| Workspace kind flag | `backend/cliff/workspace/dir_manager.py` — add `WorkspaceKind` enum, one discriminator field on the workspace record |

### V1 ↔ V2 interface contract

The two repo-scoped actions (SECURITY.md, dependabot.yml) are triggered by V2 API routes. V2 calls a single helper `workspace.create_repo_workspace(kind, repo_url, params)` that V1 owns. V1 returns a workspace_id; V2 polls the existing sidebar-state endpoint for `pr_url`, `pr_number`, and `status`. No new cross-vertical types — we reuse the existing `SidebarState` shape. **Unchanged from Revision 1 except that `kind` now takes two values instead of three.**

---

## Task breakdown (TDD-first, critical-path-ordered)

### Milestone A · Data layer (blocks everything else)

**V2 · A1** — DB migration: add `plain_description TEXT NULL` to `findings`. Add `assessments`, `posture_checks`, `completions` tables.
  - Files: `backend/cliff/db/migrations/0014_from_zero_to_secure.sql`, `backend/cliff/models/{finding,assessment,posture_check,completion}.py`
  - `completions` table shape: `id`, `assessment_id FK`, `repo_url`, `completed_at`, `criteria_snapshot JSONB` (the five criteria values at the moment of completion), `share_actions_used TEXT[]` (filled as user clicks Download / Copy text / Copy markdown — drives the v1.1 share-action-rate metric)
  - Tests first: `tests/test_migrations.py::test_0014_schema_matches_expected`

**V2 · A2** — Pydantic models + read DAOs for the three new tables.
  - Files: `backend/cliff/db/dao/{assessment,posture_check,completion}.py`
  - Tests first: `tests/db/test_assessment_dao.py` etc. — basic insert/select/upsert, `CompletionDao.record_share_action(completion_id, action)` idempotent append.

### Milestone B · Assessment engine (deterministic backend)

Unchanged from Revision 1 — B1 through B6 ship exactly as originally planned. This is the hardest technical work and the design has not moved.

**V2 · B1** — Parser registry + npm parser (`package-lock.json`, covering v1/v2/v3).
**V2 · B2** — pip parser (`Pipfile.lock` + `requirements.txt`).
**V2 · B3** — go parser (`go.sum`).
**V2 · B4** — OSV.dev client with GHSA fallback. Retries, timeout, rate-limit respect, per-package caching within one assessment.
**V2 · B5** — Posture checks module (branch protection, force pushes, secret regex scan, SECURITY.md / lockfile / dependabot / signed commits advisory).
**V2 · B6** — Assessment orchestrator: clones repo (reuses `RepoCloner` from ADR-0024), runs parsers → CVE lookup → posture, writes `assessments` + `posture_checks` rows, emits `FindingCreate` list for the ingest pipeline.

### Milestone C · Plain-language descriptions

Unchanged from Revision 1.

**V1 · C1** — Extend the `finding-normalizer` agent prompt to emit `plain_description` (2–4 sentences, no jargon, ends with a fix hint).
**V2 · C2** — Thread `plain_description` through ingest into `findings.plain_description`.

### Milestone D · API routes

**V2 · D1** — `POST /api/onboarding/repo` + `POST /api/onboarding/complete`. **Unchanged.**

**V2 · D2** — `POST /api/assessment/run`, `GET /api/assessment/status/{id}` (SSE), `GET /api/assessment/latest` (report card payload including derived grade and **completion criteria status** — previously called "badge criteria"). **Relabeled only.**

**V2 · D3** — `POST /api/posture/fix/{check_name}` — spawns a repo-workspace with the appropriate generator agent. Valid `{check_name}` values: `security_md`, `dependabot_config`. **No `badge_install`.** Returns `{workspace_id}` so the UI can poll sidebar state.
  - Files: `backend/cliff/api/routes/posture.py`
  - Tests: routes assert correct agent template is selected and workspace params are wired. **Previous D3 `POST /api/badge/add-to-readme` route removed from scope.**

**V2 · D4** — `GET /api/dashboard` aggregates latest assessment + findings counts + completion criteria status into one UI-shaped payload. **No freshness band field in the response** — the dashboard aside drops that concept in this revision.

**V2 · D5 (new)** — `POST /api/completion/{id}/share-action` — records which share action the user took (`download` / `copy_text` / `copy_markdown`). Appends to `completions.share_actions_used`. Fire-and-forget from the frontend. Drives the PRD's share-action-rate metric.
  - Files: `backend/cliff/api/routes/completion.py`
  - Tests: idempotent append, non-existent completion returns 404, invalid action value returns 422.

### Milestone E · V1 agents (parallel with D after A + B + C)

**V1 · E1** — `security_md_generator.md.j2` template. **Unchanged.**

**V1 · E2** — `dependabot_config_generator.md.j2` with ecosystem detection. **Unchanged.**

**V1 · ~~E3~~** — **Removed.** Badge installer agent is deferred to v1.2.

**V1 · E4** — `WorkspaceKind` enum + discriminator. Two kinds instead of three: `repo_action_security_md`, `repo_action_dependabot`. **Simplified.**

### Milestone F · Frontend — onboarding

Unchanged from Revision 1. F1 through F5 ship as originally planned.

### Milestone G · Frontend — dashboard and findings

**V2 · G1** — `AssessmentProgressList` (2.1). Unchanged.

**V2 · G2** — `DashboardPage` (2.2): grade ring, `CompletionProgressCard` (previously `BadgePreviewCard` — same visual, new label), vulnerabilities card, posture card, **`ScorecardInfoLine`** at the bottom of the report card (static sentence + external link to `github.com/ossf/scorecard` with `target="_blank" rel="noopener noreferrer"`). No API call for the Scorecard line.

**V2 · G3** — Extend `FindingRow` (3.1). Unchanged.

**V2 · G4** — `FindingDetailPage` (3.2). Unchanged.

**V2 · G5** — `PostureCheckItem` with compact (pass), muted (advisory), and expanded (failing) variants. Valid generator actions are now `security_md` and `dependabot_config` only. Posture card header reads "5 of 7 checks pass · 2 remaining for completion" (was "for the badge").

### Milestone H · Frontend — completion ceremony (substantially revised)

**V2 · H1** — `ShieldSVG` component. **Unchanged visual.** The shield caption text changes from "LAST VERIFIED {date}" to "COMPLETED {date}" for consistency with the new copy. Same component signature.

**V2 · H2** — `CompletionCelebration` overlay (5.1) — renamed from `BadgeEarnedCelebration`:
  - Tinted gradient backdrop, `ConfettiLayer`, scaled shield, eyebrow + headline hierarchy (`"Security complete"`, not `"Badge earned"`), `role="status" aria-live="assertive"`, `prefers-reduced-motion` fallback.
  - **Action row rebalanced per UX Rev 4:** one filled-primary `Download summary image` button (`py-3.5 px-8`) + two subordinate text-link actions below (`Copy text summary` and `Copy markdown`) separated by a ghost divider. The filled primary button scrolls the page to the `SummaryActionPanel` below (H4) on click; the text links copy directly.
  - Body copy: "The full summary panel with previews is just below."
  - On click of any share action in H2 or H4, call `POST /api/completion/{id}/share-action` (fire-and-forget) to record usage.

**V2 · H3 (new)** — `ShareableSummaryCard` component:
  - Fixed-size React component rendering a `1200×630` div with `linear-gradient(135deg, #4d44e3 0%, #575e78 100%)` background, repo name, completed date, three stats (vulns fixed, posture checks passing, PRs merged), divider, "Generated by Cliff · cliff.dev" + grade.
  - All white text uses `rgba(255,255,255,0.92)` minimum (see UX compliance section for AA rationale).
  - Component receives `{ repoName, completedAt, vulnsFixed, postureChecksPassing, prsMerged, grade }` as props; no data fetching inside.
  - Includes a `ref` forwarding pattern so the export utility (H5) can grab the DOM node.

**V2 · H4 (new)** — `SummaryActionPanel` (5.2 below the celebration): three tiles sharing the same shape (header + preview block + action button):
  - **Download tile:** metadata preview row (`image` icon + filename + `1200×630 · ~80 KB`); button triggers PNG export via H5 utility and calls `POST /api/completion/{id}/share-action` with `download`.
  - **Copy text tile:** `<pre>` preview of the tweet-sized plain text; button copies to clipboard and records `copy_text`.
  - **Copy markdown tile:** `<pre>` preview of the markdown snippet; button copies to clipboard and records `copy_markdown`.
  - Plus a footer info card: "Generated on your machine. No Cliff-hosted URL, no tracking, no account required. v1.2 will add an optional public badge with verification — not today."

**V2 · H5 (new)** — `imageExport.ts` utility. Uses `html-to-image` (add as frontend dep) to convert a DOM ref into a PNG blob, then triggers a download via a synthetic anchor click.
  - Files: `frontend/src/lib/imageExport.ts`, `frontend/package.json`
  - Tests: jsdom-based unit test that the utility calls `html-to-image.toPng` with expected options (width/height/pixelRatio).
  - Risk mitigation: test in Chrome, Firefox, and Safari before considering H5 done. Safari has known quirks with font loading in `toPng`; mitigation is to use `toBlob` with a `cacheBust: true` option and preload fonts.

**V2 · ~~H3 (old)~~** — `AddBadgeDialog` **removed.**

**V2 · H4 (old)** — Previously `FreshnessCard` + `AssessmentDiffList`. Split: **`FreshnessCard` removed.** `AssessmentDiffList` moves into G as part of the 6.2 frame work. `CompletionStatusCard` replaces `FreshnessCard` in the dashboard aside — no freshness band, shield is a `<button>` that re-opens the `SummaryActionPanel` when clicked (per UX Rev 4).

### Milestone I · Tests + docs

**V2 · I1** — E2E Playwright spec updated: onboarding → assessment → solve one finding → reach completion → **download summary image + verify PNG is produced** (was: create badge PR + verify PR opened). Assert PNG content-type on the download response. Assert `share_actions_used` row contains `download`.

**V2 · I2** — Update `docs/guides/` with an "Assessment engine" guide for contributors adding a new parser or posture check. **Unchanged.**

**V1 · I3** — E2E test for each of the **two** new agent templates in `backend/tests/e2e/test_repo_workspace_agents.py`. **Was three, now two.**

**V2 · I4 (new)** — Cross-browser smoke test for `imageExport.ts`: one Playwright test per browser (Chromium, Firefox, WebKit) that clicks Download in the celebration flow and verifies a non-empty PNG lands in the download directory.

---

## Test plan (TDD-first)

Same principles as Revision 1. Concrete additions for Revision 2:

- **`html-to-image` export:** write a failing jsdom test that asserts `exportCardAsPng(ref, filename)` calls the library with `{ pixelRatio: 2, cacheBust: true, width: 1200, height: 630 }`, then wire the utility. Then write the Playwright cross-browser test (I4) that asserts the file actually lands on disk.
- **`ShareableSummaryCard`:** Storybook snapshot + a React-Testing-Library test that asserts all six props render in the correct slots and that AA contrast values are the ones declared in the spec (regex the rendered inline styles for the `rgba` values).
- **`CompletionStatusCard` shield-as-button:** RTL test that the shield has `role="button"`, `aria-label="Re-open shareable summary card"`, and opens the summary panel on click and on `Enter` / `Space`.
- **Share-action recording:** unit test that every click on Download / Copy text / Copy markdown issues a `POST /api/completion/:id/share-action` call exactly once (debounced if double-clicked).

No milestone is considered complete until `cd backend && uv run pytest -v` and `cd backend && uv run ruff check cliff/ tests/` are green, and `cd frontend && npm test` passes.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| OSV.dev rate-limiting or downtime during the assessment | Low | GHSA fallback (ADR-0025). Degrade per-finding rather than per-assessment. Cache hits for 24h per `package@version`. |
| Lockfile format variance across package-lock versions (v1/v2/v3 differ significantly) | High | Parser must branch on `lockfileVersion`. Fixtures cover all three. Documented in parser docstring. |
| Normalizer plain-language drift — hallucinated risks, wrong severities | Medium | Evaluation fixture on 10 known CVEs, asserted via shape + presence-of-fix-hint. Human eyeball review before shipping; PRD success metric `>80% rated clear by non-security reviewer` gates the launch. |
| GitHub PAT without admin scope can't read branch protection settings | Medium | Check returns `unable to verify` (not fail). UX spec accounts for this state. |
| ~~Badge-installer agent mangles existing README~~ | — | **Risk removed with E3.** Returns in v1.2 scope. |
| **`html-to-image` cross-browser quirks (Safari font loading, CORS on external images)** | Medium | All fonts used in the summary card are `@font-face`-declared in the app, no external image dependencies, `cacheBust: true` + `skipFonts: false`. Explicit Playwright test across all three browsers (I4) before ship. Fallback if export fails: show inline error toast + "Right-click the card preview and save image" affordance. |
| **`html-to-image` adds ~80 KB gzipped to frontend bundle** | Low | Code-split: dynamic-import the utility only when the user clicks Download. No first-paint cost. Confirmed in the bundle-analyzer snapshot check that runs in CI. |
| Three workspaces running concurrently exhausts process pool | Low | Existing pool cap (ADR-0014) + idle cleanup handles this. Repo workspaces time out after first PR created. **Still applies even with two agents.** |
| Secrets regex false positives flag innocuous code as secrets | Medium | Fixed list of high-specificity patterns (AWS AKIA, GitHub `ghp_`/`ghs_`, Stripe `sk_live_`, Google API `AIza`, generic PEM blocks). Include an allow-list via `.cliff/secrets-ignore`. |

## Out of scope (per PRD-0002 Revision 2 and ADR-0025)

- SAST / DAST scanning of custom code
- Auto-remediation of branch protection or repo settings
- **Public "Secured by Cliff" README badge + PR flow** — deferred to v1.2
- **Live OpenSSF Scorecard API integration** — deferred to v1.2; v1.1 ships a static info-line only
- Badge verification server
- GitHub Action for continuous monitoring
- Multi-repo assessment
- Ruby / Java / Rust / yarn lockfile parsers (follow-up PRs, no schema change)

## ADR-0025 revision note

ADR-0025 ("Assessment engine and badge lifecycle") was written against the original badge-centric PRD. The decisions in sections 1 (assessment engine is deterministic), 3 (reuse ephemeral-workspace pattern), and 4 (phase the lockfile parsers) still hold unchanged. Section 2 ("badge state is derived") is still true but the `badges` event table has been renamed `completions` and the table shape now tracks `share_actions_used`. The badge-installer agent reference in section 3 should be removed from the "three PR-creating agents" count (now two).

I recommend a minor ADR-0025 revision pass after this plan is approved. It's a one-paragraph update, not a new ADR.

---

## Handoff

Once CEO approves this plan:

1. Ship milestones in order: A → B → (C, D, E in parallel) → F → G → H → I.
2. V1 work lives on branches prefixed `feat/from-zero-to-secure-v1-*`; V2 work on `feat/from-zero-to-secure-v2-*`.
3. Each milestone targets a separate PR to keep reviews tractable. Big-bang merge is explicitly avoided.
4. `/architect` reviews each implementation PR against this plan before `@galanko` merges.
5. For the "deliver in one day" execution plan that splits these milestones across parallel Claude Code sessions, see `docs/architecture/plans/EXEC-0002-from-zero-to-secure.md`.
