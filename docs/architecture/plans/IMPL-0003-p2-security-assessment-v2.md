# IMPL-0003-p2: Security assessment v2 — phase 2 (the rest of the owl)

**PRD:** docs/product/prds/PRD-0003-security-assessment-v2.md (rev. 2)
**Predecessor plan:** docs/architecture/plans/IMPL-0003-security-assessment-v2.md (rev. 2 — wire-contract phase, merged as PR #91)
**ADRs:** ADR-0027 (unified findings), ADR-0028 (subprocess scanners), ADR-0029 (warning token), ADR-0032 (rev. 2 dashboard payload), **ADR-0033 (pre-alpha destructive migrations — new)**
**Status:** Draft
**Date:** 2026-04-25
**Delivery:** Single PR, branch `feat/prd-0003-p2-complete`. No merge until CEO approves the visual walkthrough.

---

## Summary

PR-A (phase 1) merged the wire contract: the `SubprocessScannerRunner` class, the 15-check posture expansion, migration 010 with `tools_json` / `summary_seen_at` / `posture_check.pr_url + category`, the v0.2 dashboard route shape, the `mark-summary-seen` endpoint, the design-token CSS, and the `SeverityChip` regression test.

It deliberately deferred the parts that touch existing data or the user-visible product:

1. The engine still runs the homebrew parsers (`run_assessment_on_path` calls `osv_client.lookup_with_fallback` and `parsers.detect_lockfiles`); `SubprocessScannerRunner` exists but is not wired into the pipeline.
2. The unified `finding` table from ADR-0027 was not built; `posture_check` is still its own table.
3. The dashboard page barely changed; `ToolPillBar`, `GradeRing`'s rebuild, `CategoryHeader`, `PostureCategoryGroup`, `ScannedByLine`, `AssessmentSummary`, and the four-state `PostureCheckItem` rework did not ship.

This phase closes those three gaps in **one PR** and ends with PRD-0003 fully implemented and ready for the v0.1 alpha tag.

### Key architectural decisions for this phase

| Decision | Choice | Source |
|----------|--------|--------|
| Migration shape | Destructive — drop `finding`, drop `posture_check`, recreate `finding` with the unified schema | ADR-0033 (new) |
| Engine pipeline | `run_assessment` becomes the canonical entry point; calls `SubprocessScannerRunner.run_trivy()` + `run_semgrep()`, then posture, then persists via `to_findings.py` mappers | ADR-0027, ADR-0028 |
| Old code | Delete `parsers/` directory, `osv_client.py`, `ghsa_client.py`. No fallback, no transition period | IMPL-0003 rev. 2 (Epic 1 cleanup) |
| Frontend pixel fidelity | Match `frontend/mockups/claude-design/PRD-0003 design.html` surface-by-surface; close pixel diff before flagging done | PRD-0003 rev. 2 §"Canonical visual reference" |
| Single PR | All three phases in one branch, in order, gated by tests at each phase boundary | CEO direction (2026-04-25) |
| Manual verification | Required before flagging done. Walk every surface, capture screenshots, attach to PR | CEO direction |

> **Read this before starting:** ADR-0033 is the new ADR that authorizes the destructive migration. ADR-0032 is the contract Phase 1 already shipped against — Phase 2 is the implementation that fulfills it. PRD-0003 rev. 2 is the user-facing scope.

---

## Phase structure

Three phases ship in one PR, in order. Each phase has its own test gate; the next phase starts only after the previous one's tests are green.

```
Phase 1:  Engine cutover + parser deletion       (backend only)
Phase 2:  Unified findings model + migration     (backend only) [destructive — ADR-0033]
Phase 3:  Frontend pixel-fidelity rebuild        (frontend only)
Final:    Manual verification gate               (Gal walks every surface)
```

**Why this order.** Phase 1 makes the engine produce the right shape but persists into the old (Phase-1-merged) `posture_check` + `finding` tables. Phase 2 then unifies the schema and updates the persistence path; the dashboard route already returns the v0.2 shape so swapping its query source is a small edit. Phase 3 builds the visual surfaces against the now-real data. Reordering risks more breakage than it saves.

---

## Phase 1: Engine cutover + parser deletion

**Goal:** `run_assessment` is the canonical entry point. It clones the repo, invokes Trivy + Semgrep via `SubprocessScannerRunner`, runs the 15 posture checks, and produces an `AssessmentResult`. The homebrew parsers and OSV.dev/GHSA clients are gone.

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/assessment/engine.py` | Replace `run_assessment_on_path`'s lockfile-detection + OSV-lookup pipeline with `SubprocessScannerRunner` calls. Stop importing `osv_client` and `parsers`. Implement the real `run_assessment(repo_url, *, gh_client, ...)` so the API route can call it. Trivy failure is fatal (assessment fails); Semgrep failure is graceful (skipped step, `tools[]` entry state = `skipped`); posture failures are per-check `unknown` — they continue but don't count toward the grade |
| `backend/cliff/assessment/clone.py` | Already shipped in PR-A. Wire it into `run_assessment` |
| `backend/cliff/api/routes/assessment.py` | The `/assessment/run` route stops calling `run_assessment_on_path` and calls `run_assessment` instead. Streaming progress (`/assessment/status/{id}`) reads `tools[]` + `steps[]` from the engine's progress callbacks |
| `backend/cliff/api/routes/dashboard.py` | No changes in Phase 1 — wire shape already matches |
| `backend/tests/assessment/test_engine.py` | Rewrite engine tests against the new pipeline. Use real Trivy/Semgrep fixtures from `backend/tests/fixtures/scanners/*.json` (already in tree). Mock the subprocess at the `asyncio.create_subprocess_exec` level — do not invoke real binaries in unit tests |
| `backend/tests/api/test_integration_engine.py` | Update if it references the old pipeline |
| `backend/tests/conftest.py` | Adjust fixtures that constructed `ParsedDependency` objects |

### Files to delete

| File | Reason |
|------|--------|
| `backend/cliff/assessment/parsers/` (entire directory) | Replaced by Trivy |
| `backend/cliff/assessment/osv_client.py` | Replaced by Trivy DB |
| `backend/cliff/assessment/ghsa_client.py` | Replaced by Trivy DB |
| `backend/cliff/assessment/production_engine.py` | Vestigial alternate engine. Confirm no live caller before deleting (a quick `grep -r production_engine backend/`) |
| `backend/tests/test_parsers_*.py` | Tests for deleted code |
| `backend/tests/test_osv_client.py` | Same |
| `backend/tests/test_ghsa_client.py` | Same |

After deletion, `grep -r "from cliff.assessment.parsers" backend/` and `grep -r "from cliff.assessment.osv_client" backend/` must return zero hits.

### Engine shape (target)

```python
async def run_assessment(
    repo_url: str,
    *,
    gh_client: GithubAPI,
    runner: ScannerRunner,
    on_step: Callable[[AssessmentStep], Awaitable[None]] | None = None,
    on_tool: Callable[[AssessmentTool], Awaitable[None]] | None = None,
) -> AssessmentResult:
    """Clone -> Trivy -> Semgrep -> posture -> assemble result."""
    ...
```

The two callbacks emit progress so `/assessment/status/{id}` can stream both `steps[]` and `tools[]` incrementally per ADR-0032. The returned `AssessmentResult` includes the full `tools[]` payload that gets persisted as `tools_json` on the `assessment` row.

### Acceptance criteria for Phase 1

- [ ] `grep -r "from cliff.assessment.parsers\|from cliff.assessment.osv_client\|from cliff.assessment.ghsa_client" backend/` returns zero hits.
- [ ] `run_assessment` (not `run_assessment_on_path`) is the entry point used by every route and every test that exercises the pipeline end-to-end.
- [ ] `test_engine_step_reporting` — engine emits the six expected step keys (`detect`, `trivy_vuln`, `trivy_secret`, `semgrep`, `posture`, `descriptions`) in order.
- [ ] `test_engine_tools_emission` — engine emits a `tools[]` payload with three entries (`trivy`, `semgrep`, `posture`), states transitioning `pending → active → done`, and `result` populated on `done`.
- [ ] `test_engine_trivy_failure_is_fatal` — `SubprocessScannerRunner.run_trivy` raising fails the assessment.
- [ ] `test_engine_semgrep_failure_is_graceful` — `run_semgrep` raising marks the step `skipped`, the tool `skipped`, and the assessment continues.
- [ ] `test_engine_subprocess_env_whitelist_preserved` — wired engine still passes the env whitelist from PR-A's runner.
- [ ] `cd backend && uv run pytest -v` is green.
- [ ] `cd backend && uv run ruff check cliff/ tests/` is clean.

---

## Phase 2: Unified findings model + destructive migration

**Goal:** ADR-0027's unified `finding` table exists. Trivy vulns, Trivy secrets, Semgrep code findings, and posture failures all persist to it with a typed `type` column. The legacy `posture_check` table is gone. The dashboard route reads from the unified table.

### Files to create

| File | Purpose |
|------|---------|
| `backend/cliff/db/migrations/011_unified_findings.sql` | **Destructive migration per ADR-0033.** Drops `finding`, drops `posture_check`, creates the new unified `finding` table with the columns from ADR-0027 (`id`, `source_type`, `source_id`, `type`, `grade_impact`, `category`, `assessment_id`, `title`, `description`, `plain_description`, `raw_severity`, `normalized_priority`, `status`, `likely_owner`, `why_this_matters`, `asset_id`, `asset_label`, `raw_payload`, `pr_url`, `created_at`, `updated_at`). UNIQUE index on `(source_type, source_id)`. Indices on `(type)`, `(status)`, `(assessment_id, type)`. Leading comment lists what gets dropped (per ADR-0033 §"The migration documents what it destroys") |
| `backend/cliff/assessment/to_findings.py` | Deterministic mappers per ADR-0027 §6: `from_trivy_vulns`, `from_trivy_secrets`, `from_semgrep`, `from_posture` — all return `list[FindingCreate]` with the correct `type`, `source_type`, `source_id`, `grade_impact`, `category` |
| `backend/tests/db/test_migration_011.py` | Migration test: starts from a Phase-1-shape DB, runs the migration, asserts `finding` exists with the new columns and `posture_check` is gone |
| `backend/tests/assessment/test_to_findings.py` | Mapper tests — round-trip Trivy/Semgrep/posture fixtures into `FindingCreate` and assert `type`, `source_id`, `grade_impact`, `category` |
| `backend/tests/db/test_repo_finding_upsert.py` | UPSERT preservation tests — see "UPSERT preservation table" below |

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/models/finding.py` | Add `FindingType` literal (`dependency` \| `code` \| `secret` \| `posture`), `FindingGradeImpact` literal (`counts` \| `advisory`). Add `type`, `grade_impact`, `category`, `assessment_id`, `pr_url` to `FindingCreate`, `FindingUpdate`, `Finding` |
| `backend/cliff/db/repo_finding.py` | `create_finding` uses `INSERT ... ON CONFLICT(source_type, source_id) DO UPDATE SET ...` per the preservation table below. `list_findings` accepts `type: list[str] \| None`, `grade_impact: list[str] \| None`, `assessment_id: str \| None` filters. New `list_posture_findings(assessment_id)` helper |
| `backend/cliff/api/routes/dashboard.py` | Posture queries switch from `list_posture_checks_for_assessment` to `list_posture_findings`. The four-state projection (`pass | fail | done | advisory`) computes from `(status, pr_url, grade_impact)`. The `vulnerabilities.by_source` split queries `finding` filtered by `type` |
| `backend/cliff/db/dao/posture_check.py` | **Delete.** Callers migrate to `repo_finding.list_posture_findings` |
| `backend/cliff/models/posture_check.py` | **Delete.** `PostureCheckResult` (the in-pipeline DTO) moves to `backend/cliff/assessment/posture/__init__.py` |
| `backend/cliff/assessment/engine.py` | After Trivy / Semgrep / posture each finishes, call the matching `to_findings` mapper and persist via `create_finding`. After all scanners finish, run the stale-close pass (per ADR-0027 §"Closing stale findings"): for each `source_type` that ran successfully this assessment, mark prior open findings of the same `source_type` not seen this run as `status='closed'` with a `system_note` |
| `backend/cliff/integrations/normalizer.py` | LLM-normalizer prompt update per ADR-0027: add `type` field to the output schema with default `dependency` for ambiguous payloads. Single-sentence rule: "If the finding is a hygiene/config issue, use `posture`; if a leaked credential, use `secret`; if a SAST/code pattern, use `code`; otherwise `dependency`." No restructure |
| `backend/cliff/integrations/ingest_worker.py` | Pass `type` through from normalizer output |

### UPSERT preservation table (verbatim from IMPL-0003 rev. 2 — must be implemented exactly)

When `create_finding` hits a conflict on `(source_type, source_id)`:

| Column | On conflict | Reason |
|--------|-------------|--------|
| `id` | **Preserve** | Row identity |
| `created_at` | **Preserve** | Historical fact |
| `status` | **Preserve** | User lifecycle state (`triaged`, `in_progress`, etc.) |
| `likely_owner` | **Preserve** | May be user-edited or set by an agent |
| `plain_description` | **Preserve** | LLM-generated; expensive to regenerate |
| `why_this_matters` | **Preserve** | Agent-generated |
| `pr_url` | **Preserve** | Set when an agent merges a fix; never refresh from scanner output |
| `title` | Refresh | Scanner truth |
| `description` | Refresh | Scanner truth |
| `raw_severity` | Refresh | CVSS scores evolve |
| `normalized_priority` | Refresh | Derives from raw_severity |
| `raw_payload` | Refresh | Latest scanner payload for evidence |
| `type` | Refresh | Taxonomy — source of truth is the mapper |
| `grade_impact` | Refresh | Same |
| `category` | Refresh | Same |
| `assessment_id` | Refresh | Points at the latest scan that saw it |
| `asset_id`, `asset_label` | Refresh | Scanner-reported resource identity |
| `updated_at` | Refresh | Always bump on UPDATE branch |

### Stale-close rule (verbatim — implementation-critical)

After all scanners finish in `engine.py`, for each **scanner `source_type`** that ran successfully in *this* assessment, select existing open rows from `finding` where `source_type = X` AND `source_id NOT IN (source_ids emitted this run by X)`. Mark those `status='closed'` and append a `system_note` to `raw_payload.system_notes`.

- Scope by `source_type`, **not** by `type`. Trivy never closes Snyk-imported findings even though both share `type='dependency'`.
- Trivy secret scan uses `source_type='trivy-secret'`; Trivy vuln scan uses `source_type='trivy'`. Closed independently.
- First-run guard: if no prior assessment exists for this repo, skip the close pass entirely.
- Scanner must have run successfully — a `skipped`/errored scanner does not trigger its close pass. Absence of signal is not evidence of fix.

### Source-id conventions (verbatim)

| Type | Format | Example |
|------|--------|---------|
| `dependency` | `{PkgName}@{InstalledVersion}:{VulnID}` | `lodash@4.17.19:CVE-2021-23337` |
| `secret` | `{path}:{startLine}:{RuleID}` | `src/config.js:42:aws-access-key-id` |
| `code` | `{path}:{startLine}:{check_id}` | `app/db.py:88:python.django.security.audit.sqli` |
| `posture` | `{repo_url}:{check_name}` | `github.com/gal/repo:actions_pinned_to_sha` |
| External (LLM) | whatever the scanner provides | `snyk:SNYK-JS-LODASH-567746` |

### Acceptance criteria for Phase 2

- [ ] `grep -r "from cliff.db.dao.posture_check\|from cliff.models.posture_check" backend/` returns zero hits.
- [ ] `posture_check` table does not exist in the DB after migration 011 runs (asserted in `test_migration_011`).
- [ ] All 4 mappers in `to_findings.py` have round-trip tests against fixtures.
- [ ] UPSERT preservation tests cover all 6 preserved columns and a representative subset of the refreshed columns.
- [ ] `test_engine_closes_disappeared_findings` — scenario: scan 1 emits dep+secret, scan 2 emits only dep → scan 1's secret findings become `status='closed'`.
- [ ] `test_engine_skip_does_not_close` — scanner skipped this run → findings from prior run for that type are NOT closed.
- [ ] `test_trivy_rescan_does_not_close_external_findings` — seed a finding with `source_type='snyk'`, run a Trivy scan, assert the Snyk finding is untouched.
- [ ] `test_dashboard_grouped_posture_four_state` from PR-A still passes (it now reads from the unified table — same wire shape).
- [ ] `test_dashboard_omits_legacy_scanner_versions` from PR-A still passes.
- [ ] `cd backend && uv run pytest -v` is green.

---

## Phase 3: Frontend pixel-fidelity rebuild

**Goal:** Every PRD-0003 surface matches the corresponding `frontend/mockups/claude-design/surfaces/*.jsx` mockup. The user-visible product moves to v0.2.

### Files to create

| File | Purpose |
|------|---------|
| `frontend/src/components/dashboard/ToolPillBar.tsx` | Tool identity pills with `pending | active | done | skipped` states. **`result?: string` prop** drives the "Trivy 0.52 · 7 findings" tail. Reference: `surfaces/shared.jsx` |
| `frontend/src/components/dashboard/CategoryHeader.tsx` | Eyebrow + done/total + 80px progress rail. Reference: `surfaces/report-card.jsx` |
| `frontend/src/components/dashboard/PostureCategoryGroup.tsx` | Category header + `<ul>` of `PostureCheckItem` rows, grouped by `posture.categories[].name` |
| `frontend/src/components/dashboard/ScannedByLine.tsx` | "Scanned by" eyebrow + `ToolPillBar` (size `sm`, all `done`, with results) — used in the report-card hero divider row |
| `frontend/src/components/dashboard/AssessmentSummary.tsx` | Surface 3 interstitial — three summary cards (vulns/posture/quick wins) + grade preview + "View your report card" CTA. Reference: `surfaces/assessment-complete.jsx` (variation A) |
| `frontend/src/components/PillButton.tsx` | Primary / ghost / surface variants. Reference: `surfaces/shared.jsx` |
| `frontend/src/components/dashboard/__tests__/ToolPillBar.test.tsx` | Walks all 4 states; asserts `result.text` tail appears only on `done`; asserts active uses `animate-pulse-subtle` |
| `frontend/src/components/dashboard/__tests__/PostureCategoryGroup.test.tsx` | Mixed state row rendering; advisory not counted in progress |
| `frontend/src/components/dashboard/__tests__/AssessmentSummary.test.tsx` | Renders three cards + grade preview; CTA fires `onViewReportCard` |
| `frontend/src/components/__tests__/PillButton.test.tsx` | All 3 variants, disabled state, focus-visible ring |

### Files to modify

| File | Changes |
|------|---------|
| `frontend/src/pages/DashboardPage.tsx` | Rebuild hero per Surface 1: three-column flex (`GradeRing` 120px + narrative + last-assessed/`Re-assess`). Inset `ScannedByLine` row. Two-column row beneath: vulns card (380px) + posture card (1fr) using `PostureCategoryGroup` × 4. Narrative copy ("Nearly there." / "Off to a strong start." / etc.) is derived from `criteria_met / total` + count of fixable failing posture checks. Add the assessment-complete interstitial gate: `summary_seen_at == null && status === 'complete'` → render `<AssessmentSummary>` instead of the report card; "View your report card" calls `markSummarySeen(id)` |
| `frontend/src/components/dashboard/AssessmentProgressList.tsx` | Replace hardcoded steps with `dashboardData.steps[]` from API. Render `ToolPillBar` from `dashboardData.tools[]`. Active step expands into card-style `bg-primary-container/30` row with progress bar + detail. Pending steps render the optional `hint` chip. Add the `Previous assessment` sub-card from `/dashboard?excludeAssessmentId={runningId}` |
| `frontend/src/components/dashboard/CompletionProgressCard.tsx` | Pill meter → continuous progress bar with 11 ticks (0..10). 2-column criteria chip grid using the labeled `criteria[]` from the API. Footer copy: *"Reach 10 of 10 to unlock Grade A and the shareable summary."* |
| `frontend/src/components/dashboard/PostureCheckItem.tsx` | Reworked into four explicit state components driven by `state` (`pass`, `fail`, `done`, `advisory`). `fail` uses card-style `bg-primary-container/30`. `done` renders `Draft PR ↗` link to `pr_url`. `advisory` renders `info` icon + right-aligned `advisory` chip. Generator CTA on `fail` rows when `fixable_by` is set |
| `frontend/src/components/dashboard/GradeRing.tsx` | Confirm it accepts `size: 72 | 96 | 120 | 192` and uses Epic 0's `.grade-ring` CSS class with `--p` |
| `frontend/src/pages/onboarding/StartAssessment.tsx` | 3 steps → 4 with explicit time estimates (10s · 60s · 30s · 60s). "Powered by" `ToolPillBar` row inside `bg-surface-container-low rounded-2xl p-4` |
| `frontend/src/components/CompletionCelebration/ShareableSummaryCard.tsx` | Replace "5 criteria met" → "10 criteria met". Add `Scanned by: Trivy 0.52 · Semgrep 1.70 · 15 posture checks` line above the wordmark |
| `frontend/src/api/dashboard.ts` | Already has v0.2 types from PR-A. Add `markSummarySeen(assessmentId)` mutation hook. Add `excludeAssessmentId?` query param to `useDashboard` |

### Pixel-fidelity verification (Phase 3 only — manual gate is at the very end)

After each file change, open the running app side-by-side with `frontend/mockups/claude-design/PRD-0003 design.html` for the corresponding surface. The diff must be near-zero. Acceptable diffs: minor antialiasing, font-rendering jitter from system font stacks, scroll-bar appearance. Unacceptable: layout shift, color drift, missing states, wrong type sizes, missing accessibility affordances.

If the implementation diverges from the mockup, document the divergence in the PR description with a one-line reason. Do not silently change the design.

### Acceptance criteria for Phase 3

- [ ] All 7 new components exist with tests covering every state.
- [ ] `DashboardPage.tsx` renders the new hero with `ScannedByLine` showing per-tool result counts.
- [ ] `AssessmentSummary` renders only when `summary_seen_at == null`; clicking the CTA fires `markSummarySeen` and the next render falls through to the report card.
- [ ] Posture rows render correctly in all four states; `done` rows link to `pr_url`; `advisory` rows are visually distinct from both `pass` and `fail`.
- [ ] `CompletionProgressCard` shows the 11-tick progress bar + 10-chip grid.
- [ ] `StartAssessment` shows 4 steps with time estimates + "Powered by" tool pill row.
- [ ] `cd frontend && npm test` is green.
- [ ] `cd frontend && npm run build` is clean.

---

## Final: Manual verification gate

Before flagging the work done, the implementer (Claude Code) walks every surface manually and produces a verification report.

### What "manually" means here

`scripts/dev.sh` runs the app at `http://localhost:5173`. With a real LLM key configured (Gal's), trigger an assessment against a real test repo (a small public OSS repo will do — pick one with both lockfiles and Python/JS code so Trivy + Semgrep both run). Walk the flow.

### Verification checklist

For each item, confirm visually + capture a screenshot:

- [ ] **Onboarding step 3** — "Powered by" pill row visible, 4 step previews with time estimates, primary "Start assessment" CTA. Compare against `frontend/mockups/claude-design/surfaces/onboarding-step3.jsx`.
- [ ] **Assessment progress** — `ToolPillBar` shows three pills, the active one pulses; running step expanded into a card with progress bar + detail; previous-assessment sub-card visible if a prior assessment exists. Compare against `surfaces/assessment-progress.jsx`.
- [ ] **Assessment-complete interstitial** — three summary cards (vulns / posture / quick wins), grade preview row, primary CTA. Reload the page mid-state — interstitial should NOT re-show after the CTA was clicked (server flag persists). Compare against `surfaces/assessment-complete.jsx` (variation A).
- [ ] **Report card hero** — Grade ring, narrative copy, "Last assessed" + Re-assess button, `Scanned by` row with three tool pills carrying result counts (`Trivy 0.52 · 7 findings`, etc.). Compare against `surfaces/report-card.jsx`.
- [ ] **Posture card** — four category groups (CI supply chain, Collaborator hygiene, Code integrity, Repo configuration), each with progress rail. Mix of pass / fail / done / advisory rows. At least one `done` row links to a real PR URL (will require the prior PR-A test environment or a manually-set posture finding). Generator CTA on at least one `fail` row.
- [ ] **Completion progress card** — 11-tick progress bar, 10 chips (met/unmet), footer copy.
- [ ] **Severity colors** — medium-severity chip is the warning token (amber/orange wash), NOT green. Critical/high are red. Low is neutral. Code (Semgrep) is indigo.
- [ ] **Share card** — at Grade A (or by triggering the celebration manually), confirm "10 criteria met" + the new `Scanned by:` line above the wordmark.
- [ ] **Reduced motion** — toggle OS reduced-motion setting and confirm spinners + pulse animations stop.
- [ ] **Keyboard navigation** — tab through the dashboard, every interactive element has a visible focus ring.

### Verification artifact

A markdown file `docs/architecture/plans/IMPL-0003-p2-verification-report.md` with:
- The git SHA of HEAD of `feat/prd-0003-p2-complete`
- The OS, browser, and screen size used
- Embedded screenshots for each checklist item above
- The result of `cd backend && uv run pytest -v 2>&1 | tail -5` and `cd frontend && npm test 2>&1 | tail -5`
- A one-paragraph summary: "Ready for CEO walkthrough" or a list of remaining issues

The PR cannot be flagged ready until this file is committed.

---

## Required new ADRs

| ADR | Status | Trigger |
|-----|--------|---------|
| **ADR-0033** (already drafted alongside this plan, status `Proposed`) | Already in repo at `docs/adr/0033-pre-alpha-destructive-migrations.md` | Phase 2's destructive migration |

No other new ADRs are required. ADR-0027 (unified findings), ADR-0028 (subprocess scanners), ADR-0029 (warning token), and ADR-0032 (rev. 2 dashboard payload) are already accepted and govern this work. If the implementer encounters a decision that materially diverges from any of those, they must stop and surface it as an ADR draft for CEO review before proceeding — do not silently invent.

---

## Test plan summary

| Phase | Tests added | Coverage |
|-------|-------------|----------|
| 1 | ~10 | Engine pipeline (steps, tools emission, Trivy fatal, Semgrep graceful, env whitelist preserved); subprocess mocking; the deletion of legacy parser/OSV imports verified by grep |
| 2 | ~14 | Migration 011, four `to_findings` mappers, UPSERT preservation (6 columns), stale-close (3 scenarios incl. the source-type scoping), LLM normalizer type emission |
| 3 | ~10 | 7 new components × states; the interstitial gate by `summary_seen_at`; pixel-fidelity smoke (component renders match expected DOM tree) |
| Final | 1 | The verification report exists, both test suites are green at the recorded SHA |
| **Total new** | **~35** | (on top of the ~70+ already in PR-A) |

Run after each phase:
- `cd backend && uv run pytest -v && uv run ruff check cliff/ tests/`
- `cd frontend && npm test && npm run build`

A red test at any boundary blocks the next phase.

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Trivy/Semgrep binary not present in dev env | High in CI, low locally | The scanner runner has a clear "binary missing" error path. CI should mock the subprocess at the test level (already the convention) |
| Engine fixture regeneration drift | Medium | `backend/tests/fixtures/scanners/*.json` from PR-A are real outputs from local runs. If they go stale, regenerate from a small public OSS repo and update. Document the regeneration command in `backend/tests/fixtures/scanners/README.md` |
| Existing local DB has data the operator wanted | Low | ADR-0033 §"The migration documents what it destroys" — the migration's leading comment lists what gets dropped. The implementer flags this in the PR description so Gal can back up first if he wants |
| Pixel-fidelity drift in frontend | Medium | Mandated side-by-side comparison after each surface. Verification gate makes drift visible before merge |
| Stale-close rule mis-fires and hides still-broken findings | Low | Three explicit guards (source_type scope, scanner-must-have-run, first-run skip). Three explicit tests. Critical to get right — a regression here erodes trust |
| ADR-0033 license interpreted too liberally | Low | The ADR scopes destructive license to `finding`, `posture_check`, `ingest_job`, `agent_run`, and chat history. Anything else (`app_setting`, `credential`, `assessment`, `completion`, `repo_settings`) is preserved. The implementer asks before exceeding the scope |

---

## Done means

PRD-0003 is implemented and ready for the v0.1 alpha tag when:

1. All Phase 1, 2, 3 acceptance criteria are checked off.
2. `cd backend && uv run pytest -v` is green; `cd frontend && npm test && npm run build` is green; `cd backend && uv run ruff check cliff/ tests/` is clean.
3. The verification report (`docs/architecture/plans/IMPL-0003-p2-verification-report.md`) is committed with screenshots and "Ready for CEO walkthrough".
4. The PR description includes: the verification report link, a list of what was deleted (per ADR-0033), and a one-line confirmation that the destructive migration license was used only on the authorized tables.
5. Gal walks every surface manually and approves.

After approval and merge, ADR-0027, ADR-0028, ADR-0029, ADR-0032, and ADR-0033 flip from `Proposed` to `Accepted` in `docs/adr/README.md` (one follow-up doc commit, can be done as part of the v0.1 alpha tag commit).

---

## Implementation order — for Claude Code

When you pick this up, the workflow is two-step. Read it carefully.

### Step 1 — Plan and pause

1. Create branch `feat/prd-0003-p2-complete` from latest `main`.
2. Read every file referenced in this plan, plus the PRD, plus ADR-0033 (already in the repo).
3. Produce **`docs/architecture/plans/IMPL-0003-p2-execution-plan.md`** — the detailed execution plan with:
   - Exact migration SQL for `011_unified_findings.sql` (full file content, not just a sketch)
   - Exact engine pipeline pseudocode for `run_assessment` (the loop, the callbacks, the close pass)
   - Exact list of every test you'll write, by name, by file path
   - Exact list of every component you'll modify, by file path, with a one-line summary of the change
   - Pixel-fidelity verification methodology (how you'll do side-by-side comparison)
   - Estimated commit cadence (one commit per phase or finer)
4. Commit the execution plan and any draft ADRs (none expected beyond ADR-0033 which already exists).
5. **Stop. Surface the plan to the CEO. Wait for approval.** Do not start writing implementation code yet.

### Step 2 — Auto mode, end to end

After CEO approval:

1. Execute the plan phase by phase. Tests green at every phase boundary before moving on.
2. Do NOT pause for input between phases. Work continuously until either:
   - All three phases pass their acceptance criteria, the verification report is written, and the PR is open and ready for review, OR
   - You hit a blocker that genuinely needs human judgment (an ADR-level architectural ambiguity, a test that cannot be made to pass without changing the plan, a destructive migration that would exceed the ADR-0033 scope). In that case stop and surface the specific question — do not improvise.
3. When you hit "ready for review" — produce the verification report with screenshots, push the branch, open a PR targeting `main`, and tag `@galanko`.
4. **Do not merge.** Wait for the CEO walkthrough.

The success criterion is: the CEO walks every surface, says "yes, this is the v0.2 product", merges the PR, and tags `v0.1.0-alpha` from the resulting `main`.

---

_End of IMPL-0003-p2._
