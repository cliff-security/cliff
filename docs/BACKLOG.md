# OpenSec Backlog

> Tactical task list for both development verticals. Each skill reads this at startup to find the next unchecked item. Check off items in commits as they're completed.

## Agent Orchestration (Vertical 1)

Phase 6b — Wire sub-agents into the isolated workspace runtime:

- [x] Agent output parser + per-agent Pydantic schemas (PR 1+2)
- [x] Sidebar mapper with read-merge-write (PR 1+2)
- [x] Agent executor core engine (PR 3)
- [x] Execution API endpoints — execute, suggest-next, cancel (PR 4+5)
- [x] Pipeline orchestrator with retry loop (PR 4+5)
- [x] Error handling and resilience — stall detection, activity events (PR 6)
- [x] ADR-0021: Agent execution model
- [x] E2E tests with real OpenCode + LLM (PR 7)
- [x] Handle `permission.asked` events — backend plumbing for tool-use approval: detect OpenCode permission events, auto-approve read-tier, wait for user approval on bash/edit/mcp, grant/deny endpoints. Workspace config stays "allow" (plumbing ready for when we flip to "ask")
- [x] Executor prompt refinement — per-agent prompts with inline output contracts + retry-on-parse-failure with corrective follow-up

v1.1 — Earn the Badge (PRD-0002, UX-0002, IMPL-0002, ADR-0025):

- [ ] **C1**: Extend `finding-normalizer` agent prompt to emit `plain_description` (2–4 sentences, no jargon). Update output contract + few-shot examples. Evaluation fixture on 10 known CVEs
- [ ] **E1**: New agent template `security_md_generator.md.j2` — reads repo, writes SECURITY.md, pushes branch, opens draft PR via `gh pr create`
- [ ] **E2**: New agent template `dependabot_config_generator.md.j2` — detects ecosystems from lockfiles, writes `.github/dependabot.yml`, opens PR
- [ ] **E3**: New agent template `badge_installer.md.j2` — inserts badge markdown at top of README.md (idempotent), updates "Last verified" line, opens PR
- [ ] **E4**: `WorkspaceKind` enum (finding | repo_action) + discriminator on workspace record. Cleanup repo-action workspaces on PR completion

MVP — Agentic remediation (PRD-0001, IMPL-0001):

- [ ] **WP2: Repo access** — inject GH_TOKEN + OPENSEC_REPO_URL into workspace OpenCode process env from credential vault (ADR-0024). Agent handles clone/branch/push via bash
- [ ] **WP4: Pipeline update** — 4-agent MVP sequence (enricher → exposure → planner → executor), remove owner_resolver from defaults, update suggest_next()
- [x] **WP5: Remediation executor agent** — new `remediation_executor.md.j2` template, tool-using conversational agent, output parser + sidebar mapper for PR data
- [x] **WP5: PR creation** — agent pushes branch + creates draft PR via `gh pr create`, PR metadata in sidebar
- [x] **WP6: Status flow** — auto-advance finding status after agent completions (new → triaged → in_progress → remediated → closed)

Phase 7 — Ticket workflow (depends on Phase 6b, deferred to post-MVP):

- [ ] Ticket preview panel in workspace sidebar
- [ ] "Create ticket" action using mock Ticketing adapter
- [ ] Ticket state visible in sidebar (key, status, assignee, link)
- [ ] Close/reopen logic tied to ticket + validation state

## App Builder (Vertical 2)

### Q01R Wave 1.5 — UI happy path unblockers (EXEC-Q01R, IMPL-0012/0013/0014, ADR-0037)

Nine defects (B22–B30) found in the Q01 re-run QA campaign on 2026-05-17 against a fresh Docker container, UI-only via Claude in Chrome. Two P0 hard blockers prevent any UI-only user from producing a real remediation PR. Plans land into `main`; Wave 2 re-runs the QA after merge.

Per-bug reports: `docs/qa/QA-0001-Q01R-rerun-ui-only.md` + `docs/qa/evidence/Q01R/B*.md`.

**PR-Q01R-A — IMPL-0013 (posture autofix + default branch)**

- [ ] **Q1**: Shrink `_AUTO_FIXABLE_CHECKS` in `backend/opensec/api/routes/_level_up.py` from 4 to 2 (only `security_md`, `dependabot_config` until handlers exist) — closes B24a
- [ ] **Q2**: Add `onError` toast + inline error rendering on the Auto-fix card in `frontend/src/components/dashboard/GateRow.tsx`; parse 422 body into a useful message — closes B24b
- [ ] **Q3**: Resolve the repo's default branch via `GET /repos/{owner}/{repo}` once per assessment; pass through `RepoCoords` in `backend/opensec/assessment/posture/`; remove the `branch="main"` default — closes B23
- [ ] **Q4**: Unit tests in `test_routes_level_up.py`, `test_routes_posture.py`, `test_assessment_posture.py` per IMPL-0013

**PR-Q01R-B — IMPL-0014 + ADR-0037 (push token preflight + App permissions)**

- [ ] **Q5**: Manual ops — update `opensec-local-test` GitHub App permissions to Contents:write + Pull requests:write + Actions:read + Administration:read — closes B30 root cause
- [ ] **Q6**: Add `check_repo_push_access(token, owner, repo)` in `backend/opensec/integrations/github_app/client.py` using `GET /repos/{owner}/{repo}` `permissions.push` field
- [ ] **Q7**: Gate executor trigger on preflight in `backend/opensec/api/routes/workspaces.py`; return 412 with structured detail when push not allowed
- [ ] **Q8**: Render `agent_run.structured_output.error_details` as an inline error state in `frontend/src/components/issues/IssueSidePanel.tsx` (with "How to fix App permissions" link)
- [ ] **Q9**: Document required App permissions in `docs/guides/setup-github-app.md` (new or amended)

**PR-Q01R-C — IMPL-0012 (UI reactivity + plan flow + Issues polish)**

- [ ] **Q10**: `useOpenRouterPolling` in `frontend/src/api/aiProvider.ts` — add `window.focus` listener + fallback to `/api/integrations/ai/status` when per-session record is gone — closes B22
- [ ] **Q11**: `useAgentRuns` in `frontend/src/api/hooks.ts` — always poll at 5s while panel is open, 2s when an agent is active — closes B28 (and unlocks B29)
- [ ] **Q12**: `DefaultFooter` at `stage='plan_ready'` in `frontend/src/components/issues/IssueSidePanel.tsx` — wrap onClick in approve-then-execute sequence so sidebar.plan.approved is correctly set to true — closes B29
- [ ] **Q13**: Hydrate `severityFilter` (and `typeFilter`) from `useSearchParams` on mount in `frontend/src/pages/IssuesPage.tsx`; write back on change — closes B25
- [ ] **Q14**: Tighten `showEmptyReviewCard` condition in `IssuesPage.tsx:313` to also require `sections.todo.length === 0`; rename heading to "Manual review queue is clear" — closes B26
- [ ] **Q15**: Backend `_level_up.py` gate builders — add `first_finding_id` to gate payload; href becomes `/issues?...&open=<finding_id>` — closes B27

**Follow-up (separate work, not Wave 1.5):**

- [ ] Agent template + `WorkspaceKind` value for `code_owners_exists` (re-expand `_AUTO_FIXABLE_CHECKS`)
- [ ] Agent template + `WorkspaceKind` value for `actions_pinned_to_sha` (re-expand `_AUTO_FIXABLE_CHECKS`)
- [ ] Re-evaluate user-OAuth-token vs installation-access-token strategy when a use case for user-less execution emerges (per ADR-0037 alternatives section)
- [ ] If 5s polling cost is ever measured as a problem, migrate `useAgentRuns` to SSE via the existing `/agent-execution/stream` endpoint

### Sidenav redesign follow-up (PRD-0006, IMPL-0008-sidenav-redesign) — shipped

Closed by `feat/prd-0006-sidenav-redesign` (PR #134 / commit `b413e00`, merged 2026-05-04). 224px named rail with logo block, workspace switcher, Issues count badge, and labeled Settings footer per Claude Design's `IPSideNav`. Frontend-only, no backend, no migration.

- [x] **F1**: `SideNav.tsx` rebuilt to 224px (`w-56`) in-flow rail — logo block (`shield_lock` filled + "OpenSec" wordmark), `WorkspaceSwitcher` card with repo avatar + `owner/repo` name + URL hint + chevron (no-op in alpha), 2 named nav items, labeled Settings footer with hairline divider
- [x] **F2**: `AppLayout.tsx` moved to flex flow — `<main className="flex-1 min-w-0 overflow-x-hidden">`, no more `ml-20`
- [x] **F3**: `useOpenIssuesCount()` hook landed at `frontend/src/api/hooks.ts`, reuses the `useFindings()` cache; SideNav consumes it for the Issues badge
- [x] **F4**: Snapshot tests in `__snapshots__/SideNav.test.tsx.snap` cover active states for Dashboard / Issues / Settings

### Issues page Phase 2 (PRD-0006, IMPL-0007-issues-page-phase-2) — shipped

Closed by two PRs landed 2026-05-04: PR-A side panel + Workspace removal + Issues polish (`feat/prd-0006-phase-2-side-panel`, PR #129) and PR-B Dashboard refresh (`feat/prd-0006-phase-2-dashboard`, PR #130).

**PR-A — side panel + Workspace removal (PR #129)**

- [x] **B1**: Migration `012_phase2_columns.sql` — `finding.exception_reason` (CHECK ∈ {false_positive, accepted_risk, wont_fix, deferred}) + `finding.exception_note`
- [x] **B2**: `Finding` / `FindingCreate` / `FindingUpdate` carry exception fields; `issue_derivation` maps each reason to the matching `IssueStage` with legacy `raw_payload.exception_reason` fallback
- [x] **B3**: `POST /findings/{id}/reject` — accepts `{reason, note ≤ 280}`; re-rejecting overrides the prior reason+note
- [x] **B4**: `user_note` (≤ 2000 chars) on `POST /workspaces/{id}/agents/{type}/execute`; threaded into `remediation_planner.md.j2` `## User refinement` block; other agents accept and ignore
- [x] **F1+F3+F4+F5+F6**: `IssueSidePanel` — 480px right-edge drawer, stage-aware section ordering, sticky 72px footer (5 variants), inline Refine textarea, inline Reject reason picker (no modals)
- [x] **F2**: URL state `/issues?open=:findingId` — Esc / outside-click / browser-back close; closing clears the param
- [x] **F7**: Plans-waiting / PRs-ready sub-grouping in Review only when both buckets are non-empty
- [x] **F8**: Done collapsed by default; `[`/`]` keyboard toggle; `sessionStorage` persistence
- [x] **F9**: `WorkspacePage.tsx` (905 lines) deleted; `/workspace/:id` resolves through `WorkspaceRedirect` → `/issues?open=<finding_id>`; `HistoryCard` "View" rewired to `?open=`
- [x] **F10**: `MigrationBanner` deleted (Phase 2 is the redesign it announced)

**PR-B — Dashboard refresh (PR #130)**

- [x] **B5**: Extended `GET /dashboard` payload with history + needs-you fields (`counts.open_issues_history`, `counts.delta_pct_30d`, `counts.time_to_close_*`, `needs_you.{plans_waiting, prs_ready, critical_todo}`, `grade_history`, `severity_history`)
- [x] **F11**: `DashboardPage` rebuilt — `IssueGradeHero`, `IssueMetricCard` × 2 with `IssueSparkline` + `IssueDeltaChip`, `IssueNeedsYouLine`, `IssueGradeHistoryChart`

### Issues page Phase 1 (PRD-0006, IMPL-0006-issues-page-phase-1) — shipped

Closed by `feat/prd-0006-phase-1-issues-page` (PR #101 / commit `d8de33e`). Pinned Review section, In progress collapsed-by-default, stage-aware row actions, sidenav trim, derived `section`/`stage` on Finding response. All 13 tasks (T1–T13) shipped.

- [ ] **T1**: `issue_derivation.py` pure function + `IssueSection` / `IssueStage` / `IssueDerived` models. TDD: ≥ 18 cases in `tests/test_issue_derivation.py`. V1 consult on rule-table accuracy.
- [ ] **T2**: Wire derivation into `repo_finding.list_findings` + `get_finding`. Batch-load workspaces / agent_runs / sidebar. N+1 guard test asserts ≤ 4 SQL queries for 100 findings.
- [ ] **T3**: `IssueSeverityBadge` atom (4 kinds × 2 sizes; matches `IPSeverity` from design handoff)
- [ ] **T4**: `IssueStageChip` atom (13 stages × 5 tones; pulse-dot keyframe with reduced-motion fallback; `aria-live="polite"` on parent)
- [ ] **T5**: `IssueCountBadge` atom (3 tones; JetBrains Mono)
- [ ] **T6**: `IssueFilterChip` atom (active/inactive states; keyboard-reachable group nav)
- [ ] **T7**: `IssueRow` component — six-slot grid; stage-aware action variant (`Review plan` / `Review PR` / `Start` / chevron); click → `/workspace/:id` (Phase 1 keeps existing flow)
- [ ] **T8**: `IssuesPage` — pinned Review, In progress collapsed by default with stage breakdown, Todo flat, Done flat-dim. Replaces `FindingsPage.tsx`. Empty Review state per design.
- [ ] **T9**: `MigrationBanner` — sessionStorage-dismissed; copy locked per design
- [ ] **T10**: `IssuesHeader` — title + caption (open count · closed-last-7d · grade) + Type/Severity filter chips
- [ ] **T11**: Route rename `/findings` → `/issues` (with `<Navigate replace>` redirect; `/workspace/:id` untouched)
- [ ] **T12**: `SideNav` trim — Dashboard + Issues primary; Settings bottom-anchored. Both `/workspace` and `/history` routes stay reachable, just removed from nav.
- [ ] **T13**: Migration banner roadmap link → GitHub PRD URL (no static-file route added in Phase 1)

### v0.1 alpha blockers (PRD-0004, UX-0004, IMPL-0004, ADRs 0029–0031)

Closed by feat/prd-0004-alpha-blockers (one branch / four commits / one PR).

- [x] **T1**: Migration `009_alpha_blockers.sql` — add `kind` + `source_check_name`, make `finding_id` nullable, create partial unique index `idx_workspace_active_per_check`. TDD via `tests/test_migration_009.py`
- [x] **T2**: Workspace DB insert on `spawn_repo_workspace` — extend `_DefaultRepoWorkspaceSpawner` to INSERT with `kind` + `source_check_name` + `state='pending'`; filesystem tear-down on DB failure
- [x] **T3**: 409 guard on `POST /api/posture/fix/{check_name}` — catch `IntegrityError`, look up existing non-terminal workspace, return `{error: "workspace_already_running", workspace_id, check_name}`
- [x] **T4**: `POST /api/settings/providers/test` — probe OpenCode with 8s timeout and classify response into `{ok, latency_ms, error_code, error_message}`; adds a `timeout` kwarg to `OpenCodeClient.send_message`
- [x] **T5**: Tailwind `warning` token family — `warning` / `warning-container` / `on-warning-container` / `warning-dim` per ADR-0029
- [x] **T6**: Delete `TopBar.tsx` — retire the non-functional top chrome; `AppLayout` drops the component
- [x] **T7**: SideNav rework — Dashboard · Findings · History · Integrations · (spacer) · Settings; tonal active-state pill, no border violations
- [x] **T8**: `Run assessment` / `Re-run assessment` button on Dashboard — new `RunAssessmentButton` + `useRunAssessment` hook wired to `POST /api/assessment/run`
- [x] **T9**: Post-onboarding redirect → `/dashboard` — `StartAssessment.tsx` already redirects here; empty-state copy updated
- [x] **T10**: PostureCheckItem rework — 4-state matrix (to_do / running / succeeded / failed) with leading `w-14` status column, action-slot variants, new `useWorkspaceStatus` hook
- [x] **T11**: Posture progress rail — `h-1.5 w-40 bg-tertiary` rail above PostureCard heading, proportional to passing checks
- [x] **T12**: "Test connection" button on ProviderSettings — `useProviderTest` hook, result chip with error-code copy map, 1-edit typo suggestion on `model_not_found`
- [x] **T13**: Description fallback — new `resolveFindingDescription` + `DescriptionFallbackNote`; applied to `FindingRow` and `FindingDetailPage`
- [x] **T14**: Medium-severity chip → warning token — swaps `text-tertiary` / `bg-tertiary-container` for `text-warning` / `bg-warning-container/40 text-on-warning-container` in DashboardPage + SeverityBadge

### v1.1: Earn the Badge (PRD-0002, UX-0002, IMPL-0002, ADR-0025)

**Milestone A — Data layer (blocks everything else)**

- [ ] **A1**: Migration `0014_earn_the_badge.sql` — add `findings.plain_description` column, create `assessments`, `posture_checks`, `badges` tables. TDD: `test_0014_schema_matches_expected` first
- [ ] **A2**: Pydantic models + read DAOs for `assessments`, `posture_checks`, `badges` — `backend/opensec/db/dao/{assessment,posture_check,badge}.py`

**Milestone B — Assessment engine (deterministic Python, no LLM)**

- [ ] **B1**: Parser registry + npm parser (`package-lock.json` v1/v2/v3). Fixture tests against three real lockfiles
- [ ] **B2**: pip parser (`Pipfile.lock` + `requirements.txt`). Fixtures + tests
- [ ] **B3**: go parser (`go.sum`). Fixtures + tests
- [ ] **B4**: OSV.dev HTTP client with GHSA fallback — retries, timeout, per-(package@version) caching within one assessment
- [ ] **B5**: Posture checks module — branch protection, force pushes, secrets regex scan (AWS/GitHub/Stripe/Google/PEM patterns), SECURITY.md/lockfile/dependabot existence, signed commits advisory
- [ ] **B6**: Assessment orchestrator `engine.py` — clones via `RepoCloner` (ADR-0024), runs parsers → CVE lookup → posture, writes rows, emits `FindingCreate` for ingest pipeline

**Milestone C — Plain-language (V2 side of C1)**

- [ ] **C2**: Thread `plain_description` through ingest worker + findings response schema

**Milestone D — API routes**

- [ ] **D1**: `POST /api/onboarding/repo` + `POST /api/onboarding/complete` + `onboarding_completed` settings flag
- [ ] **D2**: `POST /api/assessment/run` + `GET /api/assessment/status/{id}` (SSE progress) + `GET /api/assessment/latest` (derived grade + badge criteria in payload)
- [ ] **D3**: `POST /api/posture/fix/{check_name}` + `POST /api/badge/add-to-readme` — spawn repo-kind workspaces, return `{workspace_id}` for sidebar polling
- [ ] **D4**: `GET /api/dashboard` — UI-shaped aggregated payload (findings counts + posture + badge status + freshness band)

**Milestone F — Frontend onboarding**

- [ ] **F1**: Router entry — redirect to `/onboarding/welcome` while `settings.onboarding_completed === false`. `OnboardingLayout` + shared `StepProgress`
- [ ] **F2**: `WelcomePage` (UX frame 1.0) — single "Get started" CTA
- [ ] **F3**: `ConnectRepoPage` (frames 1.1/1.2/1.3) — single "Verify and continue", inline validation, 700ms auto-advance. `TokenHowToDialog` modal (frame 1.1a) with scrim + blur backdrop
- [ ] **F4**: `ConfigureAIPage` (frame 1.4) — provider cards + key + optional model
- [ ] **F5**: `StartAssessmentPage` (frame 1.5) — three-step preview + "Start assessment"

**Milestone G — Frontend dashboard + findings**

- [ ] **G1**: `AssessmentProgressList` (frame 2.1) — SSE consumer of `/api/assessment/status/{id}`
- [ ] **G2**: `DashboardPage` (frame 2.2) — `GradeRing`, `BadgePreviewCard`, `CriteriaMeter`, vulns card, posture card
- [ ] **G3**: Extend `FindingRow` (frame 3.1) — plain-language headline, muted tech line, reweighted Solve buttons (filled on top severity only)
- [ ] **G4**: `FindingDetailPage` + `TechnicalDetailsPanel` (frame 3.2) — plain body + collapsible tech details + primary/text/overflow action bar
- [ ] **G5**: `PostureCheckItem` (compact/muted/expanded variants) + `GenerateFilePreview` (frame 4.1) wired to `/api/posture/fix/*`

**Milestone H — Completion ceremony + summary card** (per IMPL-0002 Revision 2)

- [ ] **H1**: `ShieldSVG` (scale-responsive). "LAST VERIFIED" → "COMPLETED" caption
- [ ] **H2**: `CompletionCelebration` (frame 5.1) — `ConfettiLayer`, eyebrow/headline ("Security complete"), `role="status" aria-live="assertive"`, `prefers-reduced-motion` fallback; filled-primary `Download summary image` + two text-link share actions
- [ ] **H3**: `ShareableSummaryCard` — `1200×630` div with sanctioned gradient, all white text ≥ `rgba(255,255,255,0.92)`; `ref`-forwarded for PNG export
- [ ] **H4**: `SummaryActionPanel` — three tiles (download PNG / copy text / copy markdown); each click posts to `/api/completion/{id}/share-action`
- [ ] **H5**: `imageExport.ts` — dynamic-imported `html-to-image`; `{ pixelRatio: 2, cacheBust: true, width: 1200, height: 630 }`

**Milestone I — Integration + E2E + docs** (Session G)

- [ ] **I0**: Replace DI seam defaults — `get_assessment_engine` returns Session A's real engine; `get_repo_workspace_spawner` returns Session C's shim on `WorkspaceDirManager.create_repo_workspace`. Two-line body swap; no route/protocol changes. Validate the three gaps in `docs/known-issues/session-b-handoff-gaps.md`
- [ ] **I1**: E2E Playwright: onboarding → assessment → solve one finding → reach completion → download summary image → verify PNG + `completion.share_actions_used` contains `download`
- [ ] **I2**: Contributor guide `docs/guides/assessment-engine.md` — how to add a parser or posture check
- [ ] **I3**: Remove MSW handlers for the eight real routes; keep everything else mocked
- [ ] **I4**: Cross-browser (Chromium/Firefox/WebKit) smoke for `imageExport.ts`
- [ ] **I5**: `OPENSEC_V1_1_FROM_ZERO_TO_SECURE_ENABLED` feature flag in `backend/opensec/config.py` (default `false`); guard the onboarding-wizard redirect

### Priority 1: Simplification (tech debt from architecture review, 2026-04-06)

These clean up over-engineering identified during the integration strategy review. Do these first — they reduce code surface before adding new features.

- [x] Remove audit hash-chain: strip `prev_hash`, `event_hash`, `verify_chain()` from `audit.py`, remove `GET /api/audit/verify` route, simplify `_write_event` to direct insert without hash computation. Keep structured audit logging and async queue. (~40 lines removed from production, simplify `repo_audit` accordingly)
- [x] Remove hash-chain from audit DB schema: drop `prev_hash` and `event_hash` columns from `audit_log` table migration, add a new migration to remove them if table exists
- [x] Remove hash-chain tests: strip chain-related assertions from `tests/test_audit.py` (keep event logging tests)
- [x] Simplify registry loader: remove `clear_cache()`, `_cache` global, and `registry_dir` override from `registry/__init__.py`. Load once at import time. For tests, use monkeypatch on the loaded list directly

### Priority 2: Merge and stabilize current branch

- [x] Merge connection testing framework branch (`feat/connection-testing-framework`) into main via PR

### Priority 3: Core integration wiring (agentic plane only)

These wire integrations into the workspace runtime so agents can use MCP tools during remediation.

- [x] Integrations page: connection status indicators and test-from-UI flow (uses existing health monitor + connection testers)
- [x] Finding normalization via dedicated agent: create `finding-normalizer` agent (`.opencode/agents/`), `POST /api/findings/ingest` route accepts `{ source, raw_data[] }`, uses singleton OpenCode process to extract structured fields into `FindingCreate`. Low-cost design: tight prompt with few-shot examples, no tool use, batch support. Works with any scanner format. See ADR-0022
- [x] Async chunked ingest: replace synchronous ingest with job-based async processing. `POST /api/findings/ingest` returns job ID immediately, background worker chunks raw data into batches of 10, processes each independently. Includes: `ingest_job` DB table + migration, background worker coroutine (FastAPI lifespan), `GET /api/findings/ingest/{job_id}` progress endpoint, cancel endpoint, token estimation, dry-run mode, model override field. See ADR-0023
- [x] Ingest progress UI: frontend polling for job status, progress bar, error display, cancel button. Replace existing synchronous ingest result handling
- [ ] Jira write-back workflow: ticket creation from workspace using Jira MCP server (zero custom code — registry entry + credential schema only)
- [ ] Status write-back from workspace to source system (Wiz `wiz_update_finding_status` tool already exists)

### Priority 4: Additional vendor wrappers

Connection testers are a UI convenience, not mandatory for new integrations. Only add a tester if the vendor has no MCP server that validates credentials on startup.

- [ ] Additional vendor wrapper: Snyk (thin MCP wrapper, follow Wiz pattern)
- [ ] Additional vendor wrapper: Tenable (thin MCP wrapper)

### Priority 5: Design system compliance (UX audit 2026-04-09)

Systematic violations found across 13 of 17 components. See `docs/design/specs/UX-000-current-state-audit.md` for full audit.

**P0 — Fix systematic violations (affects all pages):**

- [ ] Create `ghost-border` Tailwind utility: add `shadow-[0_0_0_1px_rgba(var(--outline-variant),0.15)]` to config. This replaces all `border` usage with the design system's ghost border pattern
- [ ] SideNav: replace `border-r border-outline-variant/20` with tonal bg shift, replace `border-r-2 border-primary` active indicator with background highlight (`bg-primary-container/30`)
- [ ] TopBar: replace `border-b-2 border-primary` active nav indicator with background highlight or box-shadow underline. Replace `bg-green-500` health dot with `bg-tertiary`
- [ ] ListCard: remove `border border-transparent` and `hover:border-primary/5`, rely on shadow-only hover
- [ ] WorkspaceSidebar: replace `border-l border-surface-container` with tonal bg shift, replace `border border-surface-container/50` section borders with spacing + background
- [ ] ActionChips: replace `border border-primary/10` with tonal background (`bg-primary-container/10`)
- [ ] ActionButton: replace `border border-outline-variant/30` (outline variant) with ghost-border utility or tonal bg
- [ ] ResultCard: replace 3 border instances (card, header divider, button area) with tonal layering
- [ ] AgentRunCard: replace 3 border instances across states, replace `bg-indigo-50/80`/`border-indigo-100` with `bg-primary-container/30`
- [ ] HistoryCard: replace state badge borders with bg-only badges, replace `text-green-700`/`bg-green-100`/`border-green-200` with `text-tertiary`/`bg-tertiary-container/30`
- [ ] HistoryDetail: replace `border-t border-surface-container/50` separator with spacing + tonal bg, replace `border border-surface-container/80` on message bubbles
- [ ] Replace all arbitrary green colors with `tertiary` tokens: grep `green-` in `frontend/src/` — affects ProviderSettings, IntegrationSettings, TopBar, HistoryCard
- [ ] Replace all arbitrary red colors with `error` tokens: grep `red-` in `frontend/src/` — affects IntegrationSettings

**P1 — Missing UX patterns (reliability and accessibility):**

- [ ] Create `ErrorState` component (like EmptyState but for API failures): icon, title, subtitle, retry button
- [ ] Add error boundaries to FindingsPage, HistoryPage, WorkspacePage, SettingsPage — catch render errors, show ErrorState
- [ ] Add `loading` prop to ActionButton: shows spinner, disables click during async
- [ ] Add `loading` prop to ActionChips: show spinner on the active chip while agent runs
- [ ] Add `focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2` to all interactive elements: ActionButton, ActionChips, ListCard, nav items, tabs
- [ ] Create `ConfirmDialog` component: modal with title, message, confirm/cancel buttons. Use for: resolve workspace, delete API key, delete integration

### Priority 6: Mockup drift fixes (UX audit 2026-04-09)

Closes gaps between Stitch mockups (`frontend/mockups/html/`) and current implementation. See `docs/design/specs/UX-000-current-state-audit.md`.

**History page (high drift):**

- [ ] Stats dashboard bento grid at top of History page: total resolved count, average time to fix, success rate — requires new API endpoint for workspace stats
- [ ] Pagination for history list (currently loads all, won't scale)
- [ ] Date range / calendar filter for history
- [ ] "Showing X of Y workspaces" counter text
- [ ] "Reuse Plan" button on HistoryCard — copy a past remediation plan into a new workspace

**Settings page (high drift):**

- [ ] Internal sidebar navigation: Model settings, Agent settings, Workspace defaults, App preferences — currently flat sections, mockup shows tabbed sidebar
- [ ] Agent settings section: threat hunting toggle, auto-remediation toggle, auto-update sidebar toggle
- [ ] Workspace defaults section: default action checkboxes (quarantine, notify admin, ignore low-risk, log only)
- [ ] App preferences section: language dropdown, notification channel checkboxes
- [ ] Save/Discard buttons fixed at page footer

**Findings page (medium drift):**

- [ ] "Sentinel Insights" right sidebar panel — contextual AI summary of findings state (e.g., "3 critical findings share the same CVE, consider batch remediation")
- [ ] Educational/promotional card ("Automated remediation is learning from your patterns")
- [ ] Blocked finding state with opacity/grayscale visual treatment

**Workspace page (low drift):**

- [ ] Structured agent result cards: replace raw markdown output with card-based results matching mockup — headers, confidence badges, evidence/recommendation sections
- [ ] Enhanced "Agent Running" card with animated dots + descriptive text

**Integrations page:**

- [ ] Create dedicated IntegrationsPage route (currently embedded in Settings) — mockup shows a standalone page with richer layout

### MVP — Frontend (PRD-0001, IMPL-0001):

- [x] **WP1: Docker first-run** — seed demo mode (OPENSEC_DEMO env var), `gh` CLI in Docker image
- [ ] **WP2: Repo settings UI** — RepoSettingsSection component (URL + PAT + test connection), "solve without repo" guard dialog
- [ ] **WP3: Import UX** — ImportDialog component (file upload + paste JSON tabs), ImportButton in toolbar, empty state with import CTA
- [ ] **WP7: Structured result cards** — EnricherResultCard, ExposureResultCard, PlannerResultCard, RemediationResultCard, ConfidenceBadge
- [ ] **WP7: Error handling** — ErrorState component, ErrorBoundary on all pages, API error states with retry
- [x] **WP5: Plan approval card** — PlanApprovalCard component (approve/modify plan before executor runs)
- [x] **WP5: PR display** — PRStatusBadge, sidebar "Pull request" section, PR link in FindingRow
- [x] **WP6: Status badges** — status color progression per UX-0001, PR link icon in findings table
- [ ] **WP4: Suggest-next wiring** — highlight recommended action chip, SuggestedActionHighlight styling, chip states (default/suggested/running/completed/disabled)

### Priority 7: Findings page and UI gaps

- [ ] Findings page: search by title/asset/CVE (Phase 4 gap)
- [ ] Findings page: "Why this matters" preview on hover/expand (Phase 4 gap)
- [ ] Settings page: model/provider configuration improvements
- [x] Permission approval UI: SSE listener for `permission_request` events in WorkspacePage, approval card component (tool name, command patterns, approve/deny buttons), POST to `/api/workspaces/{id}/agent-runs/{run_id}/permission`. Backend plumbing done in Phase 6b PR #34. Also needs: flip workspace `opencode.json` from `"allow"` to `"ask"` for bash/edit

### Priority 8: Packaging (depends on Phase 6b + Phase 7 completion)

- [x] Startup migration runner
- [x] Seed demo data mode (`OPENSEC_DEMO=true`)
- [ ] Install + upgrade documentation
- [ ] First tagged release (v0.1.0-alpha)

### Deferred (not in MVP scope)

These are parked until the operational plane is needed. ADR-0020 has been downgraded to "Proposed" status.

- Operational plane: scheduled sync/polling jobs (revisit when ADR-0020 is re-accepted)
- Webhook ingestion handlers for finding sources
- Hash-chain tamper evidence for audit log (re-add for enterprise/multi-user edition)
- App-level conversational interface: chat-as-shell for the main app (finding upload via conversation, collector configuration, integration setup, natural-language queries across findings). Requires ADR-0022 accepted + Phase 6b complete. Revisit after v0.1.0-alpha

## Cross-cutting

- [x] ADR-0021: Agent execution model (direct invocation, advisory pipeline, filesystem checkpoints)
