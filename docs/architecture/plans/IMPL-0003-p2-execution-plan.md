# IMPL-0003-p2 — Execution plan

**Status:** Draft (Step 1 — awaiting CEO approval)
**Branch (to be created in Step 2):** `feat/prd-0003-p2-complete`
**Plan file destination (to be committed in Step 2):** `docs/architecture/plans/IMPL-0003-p2-execution-plan.md`
**Predecessor:** PR #93 (PR-A, merged commit `39f2202`)
**Authoritative spec:** `docs/architecture/plans/IMPL-0003-p2-security-assessment-v2.md`
**ADR gates:** ADR-0027 (unified findings), ADR-0028 (subprocess-only), ADR-0029 (warning token), ADR-0032 (rev. 2 dashboard payload), ADR-0033 (pre-alpha destructive migrations)

---

## Context

PR-A merged the wire contract for PRD-0003 v0.2 — `SubprocessScannerRunner`, the 15-check posture expansion, migration 010 (`assessment.tools_json`, `assessment.summary_seen_at`, `posture_check.pr_url`, `posture_check.category`), the v0.2 dashboard route shape, the `mark-summary-seen` endpoint, design-token CSS, and the `SeverityChip` regression test. It deliberately did not touch user-visible data or product surfaces.

This PR (PR-B) closes the three remaining gaps in **one branch** so PRD-0003 can flip to "implemented" and the v0.1 alpha tag becomes possible:

1. The engine still uses homebrew lockfile parsers + OSV/GHSA HTTP clients. Phase 1 cuts that over to `SubprocessScannerRunner.run_trivy()` + `run_semgrep()`, deletes `parsers/`, `osv_client.py`, `ghsa_client.py`, `production_engine.py`.
2. `posture_check` is still a parallel table. Phase 2 destroys it and the legacy `finding` table, then recreates a unified `finding` per ADR-0027 (typed `type`, `grade_impact`, `category`, `assessment_id`, `pr_url`). Authorized by ADR-0033 (pre-alpha license).
3. The dashboard surfaces are barely changed. Phase 3 rebuilds them pixel-for-pixel against `frontend/mockups/claude-design/` (7 new components, 5 page rebuilds, the four-state `PostureCheckItem`).

The gate at the very end is a manual visual walkthrough; Gal merges only after he walks every surface.

---

## What PR-A already shipped (verified — read-only walk against `main`)

| Path | State on `main` |
|------|-----------------|
| `backend/cliff/assessment/scanners/{__init__,runner,verify,models}.py` | exists; `SubprocessScannerRunner` ready |
| `backend/cliff/assessment/posture/{ci_supply_chain,collaborator_hygiene,code_integrity,__init__}.py` | exists; `run_all_posture_checks()` returns 15 `PostureCheckResult` rows |
| `backend/cliff/assessment/clone.py` | exists (RepoCloner per ADR-0024) |
| `backend/cliff/db/migrations/010_assessment_v2_dashboard.sql` | adds `assessment.tools_json`, `assessment.summary_seen_at`, `posture_check.pr_url`, `posture_check.category` |
| `backend/cliff/api/routes/dashboard.py` | returns the v0.2 shape but reads `posture_check` via `list_posture_checks_for_assessment()` |
| `backend/tests/api/test_dashboard_v2_payload.py` | 10 contract tests, green |
| `backend/cliff/assessment/engine.py` | still uses `parsers.detect_lockfiles` + `osv_client.lookup_with_fallback` (Phase 1 fixes) |
| `backend/cliff/assessment/parsers/`, `osv_client.py`, `ghsa_client.py`, `production_engine.py` | still in tree (Phase 1 deletes) |
| `backend/cliff/db/dao/posture_check.py`, `backend/cliff/models/posture_check.py` | still in tree (Phase 2 deletes) |
| `frontend/src/components/dashboard/SeverityChip.tsx` | exists with regression test (medium = warning token, code = indigo) |
| `frontend/src/pages/DashboardPage.tsx` | barely changed (Phase 3 rebuilds) |
| `frontend/src/api/dashboard.ts` | already typed against v0.2 wire shape |
| `frontend/tailwind.config.ts` | already has warning tokens per ADR-0029 |

---

## Phase 1 — Engine cutover + parser deletion

**Goal.** `run_assessment(repo_url, *, gh_client, runner, on_step, on_tool)` becomes the canonical entry point. It clones via `RepoCloner`, runs Trivy + Semgrep through `SubprocessScannerRunner`, runs the 15 posture checks, and returns an `AssessmentResult` with the full `tools[]` payload populated. The homebrew parsers and OSV/GHSA HTTP clients are gone.

### Files modified

| File | Change |
|------|--------|
| `backend/cliff/assessment/engine.py` | Rewrite from the `run_assessment_on_path`-shaped function to a real `run_assessment(repo_url, *, gh_client, runner, on_step, on_tool)`. Stop importing `osv_client`/`parsers`. Trivy raise → fatal; Semgrep raise → graceful (tool/state `skipped`); per-check posture exception → status `unknown`, run continues |
| `backend/cliff/api/routes/assessment.py` | `/assessment/run` calls `run_assessment(...)`; `/assessment/status/{id}` reads from a per-assessment progress store the engine populates via `on_step` + `on_tool` |
| `backend/cliff/api/_background.py` | Replace `ProductionAssessmentEngine`/`run_assessment_on_path` with the new `run_assessment`; pass the singleton `SubprocessScannerRunner` and `RepoCloner` from app state |
| `backend/tests/conftest.py` | Drop fixtures that built `ParsedDependency`/`Advisory` objects |
| `backend/tests/assessment/test_engine.py` | Full rewrite (test list below) |
| `backend/tests/api/test_integration_engine.py` | Update to drive the new pipeline (real `SubprocessScannerRunner` with mocked subprocess) |

### Files deleted

| Path | Notes |
|------|-------|
| `backend/cliff/assessment/parsers/` (entire directory) | replaced by Trivy DB |
| `backend/cliff/assessment/osv_client.py` | replaced by Trivy DB |
| `backend/cliff/assessment/ghsa_client.py` | replaced by Trivy DB |
| `backend/cliff/assessment/production_engine.py` | vestigial; only call site is `_background.py`, which moves to direct `run_assessment` import |
| `backend/tests/assessment/test_npm_parser.py`, `test_go_parser.py`, `test_pip_parser.py` | tests for deleted code |
| `backend/tests/assessment/test_osv_client.py` | same |

After deletion: `grep -r "from cliff.assessment.parsers\|from cliff.assessment.osv_client\|from cliff.assessment.ghsa_client" backend/` returns zero hits.

### Engine pseudocode — `run_assessment`

```python
# backend/cliff/assessment/engine.py

async def run_assessment(
    repo_url: str,
    *,
    gh_client: GithubAPI,
    runner: ScannerRunner,
    cloner: RepoCloner,
    db: aiosqlite.Connection,           # for the close pass (Phase 2)
    on_step: Callable[[AssessmentStep], Awaitable[None]] | None = None,
    on_tool: Callable[[AssessmentTool], Awaitable[None]] | None = None,
    branch: str = "main",
) -> AssessmentResult:
    """Clone -> Trivy -> Semgrep -> posture -> assemble result."""

    assessment_id = str(uuid.uuid4())
    coords = _coords_from_repo_url(repo_url, branch=branch)

    tools: dict[str, AssessmentTool] = {
        "trivy":   AssessmentTool(id="trivy",   label="Trivy",   icon="bug_report", state="pending"),
        "semgrep": AssessmentTool(id="semgrep", label="Semgrep", icon="code",       state="pending"),
        "posture": AssessmentTool(id="posture", label="15 posture checks", icon="rule", state="pending"),
    }
    await _emit_initial_tools(on_tool, tools)

    # ---- 1. Clone ----
    await _emit_step(on_step, AssessmentStep(key="detect", status="active"))
    async with cloner.clone(repo_url, branch=branch) as repo_path:
        await _emit_step(on_step, AssessmentStep(key="detect", status="done"))

        # ---- 2. Trivy vulns ----
        await _set_tool(on_tool, tools, "trivy", state="active")
        await _emit_step(on_step, AssessmentStep(key="trivy_vuln", status="active"))
        try:
            trivy_result = await runner.run_trivy(repo_path)
        except ScannerError as e:                       # fatal
            await _set_tool(on_tool, tools, "trivy", state="skipped")
            raise AssessmentFailed("trivy", e) from e
        # Trivy yields both vuln + secret findings; emit two visible steps but keep one tool
        await _emit_step(on_step, AssessmentStep(key="trivy_vuln", status="done"))
        await _emit_step(on_step, AssessmentStep(key="trivy_secret", status="done"))
        # Phase 2 only: persist via to_findings.from_trivy_vulns + from_trivy_secrets

        # ---- 3. Semgrep ----
        await _set_tool(on_tool, tools, "semgrep", state="active")
        await _emit_step(on_step, AssessmentStep(key="semgrep", status="active"))
        try:
            semgrep_result = await runner.run_semgrep(repo_path)
            semgrep_ran = True
        except ScannerError as e:                       # graceful
            logger.warning("semgrep failed; continuing without it: %s", e)
            semgrep_result = None
            semgrep_ran = False
            await _set_tool(on_tool, tools, "semgrep", state="skipped")
            await _emit_step(on_step, AssessmentStep(key="semgrep", status="skipped"))
        else:
            await _emit_step(on_step, AssessmentStep(key="semgrep", status="done"))
        # Phase 2 only: if semgrep_ran, persist via to_findings.from_semgrep

        # ---- 4. Posture (15 checks) ----
        await _set_tool(on_tool, tools, "posture", state="active")
        await _emit_step(on_step, AssessmentStep(key="posture", status="active"))
        posture_results = await run_all_posture_checks(
            repo_path, gh_client=gh_client, coords=coords, assessment_id=assessment_id,
        )
        # Phase 2 only: persist failing/advisory via to_findings.from_posture
        await _emit_step(on_step, AssessmentStep(key="posture", status="done"))

    # ---- 5. Compute results & finalize tools ----
    # tools[].result populated AFTER the close pass so counts reflect persisted state
    trivy_count   = len(trivy_result.vulnerabilities) + len(trivy_result.secrets)
    semgrep_count = len(semgrep_result.findings) if semgrep_ran else 0
    posture_pass  = sum(1 for r in posture_results if r.status == "pass")

    await _set_tool(on_tool, tools, "trivy",
        state="done", version=trivy_result.scanner.version,
        result=AssessmentToolResult(kind="findings_count", value=trivy_count, text=f"{trivy_count} findings"))
    if semgrep_ran:
        await _set_tool(on_tool, tools, "semgrep",
            state="done", version=semgrep_result.scanner.version,
            result=AssessmentToolResult(kind="findings_count", value=semgrep_count, text=f"{semgrep_count} findings"))
    await _set_tool(on_tool, tools, "posture",
        state="done",
        result=AssessmentToolResult(kind="pass_count", value=posture_pass, text=f"{posture_pass} pass"))

    # ---- 6. Phase-2 close pass ----
    # For each scanner that ran successfully, close prior open findings whose source_id
    # was not seen this run. Scope by source_type, NOT type. First-run guard inside.
    await _close_disappeared_findings(db, assessment_id=assessment_id, runs={
        "trivy":         {"ran": True,         "ids": _trivy_vuln_source_ids(trivy_result)},
        "trivy-secret":  {"ran": True,         "ids": _trivy_secret_source_ids(trivy_result)},
        "semgrep":       {"ran": semgrep_ran,  "ids": _semgrep_source_ids(semgrep_result) if semgrep_ran else set()},
        "cliff-posture": {"ran": True,       "ids": _posture_source_ids(repo_url, posture_results)},
    })

    # ---- 7. Snapshot + grade ----
    await _emit_step(on_step, AssessmentStep(key="descriptions", status="active"))
    snapshot = _build_snapshot(trivy_result, semgrep_result, posture_results)
    grade    = derive_grade(snapshot, ...)
    await _emit_step(on_step, AssessmentStep(key="descriptions", status="done"))

    return AssessmentResult(
        assessment_id=assessment_id,
        repo_url=repo_url,
        grade=grade,
        criteria_snapshot=snapshot,
        tools=list(tools.values()),
        posture_checks=[r.model_dump() for r in posture_results],
    )
```

Notes:
- The six step keys (`detect`, `trivy_vuln`, `trivy_secret`, `semgrep`, `posture`, `descriptions`) are emitted in order. `trivy_vuln` and `trivy_secret` are visual stages of one tool — the **tool** state transitions once.
- `on_tool` is invoked for every transition: pending → active → done|skipped. Initial broadcast emits all three pending pills so the UI can render the bar from t=0.
- `AssessmentFailed("trivy", ...)` is the fatal-Trivy exception path. The route catches it, marks the assessment row `status='failed'`, and surfaces the error.
- `_close_disappeared_findings` is implemented inside `repo_finding.py` (Phase 2). It is a no-op if no prior assessment exists for `repo_url`.

### Phase 1 acceptance criteria

- `grep -r "from cliff.assessment.parsers\|from cliff.assessment.osv_client\|from cliff.assessment.ghsa_client" backend/` → zero hits
- `grep -r "production_engine\|run_assessment_on_path" backend/` → zero hits
- `cd backend && uv run pytest -v -m 'not e2e'` → green
- `cd backend && uv run ruff check cliff/ tests/` → clean

---

## Phase 2 — Unified findings model + destructive migration (ADR-0027 + ADR-0033)

**Goal.** One `finding` table with a typed `type` column. Trivy vulns / secrets, Semgrep, and posture failures all UPSERT through `create_finding`. The legacy `posture_check` table is dropped. The dashboard route reads from the unified table.

### Migration 011 — exact full file content

`backend/cliff/db/migrations/011_unified_findings.sql`:

```sql
-- 011_unified_findings.sql
-- ADR-0027 (unified findings model) + ADR-0033 (pre-alpha destructive migrations).
--
-- Authorized destructive scope (ADR-0033 §1):
--   DROP TABLE finding         -- regeneratable by re-running an assessment
--   DROP TABLE posture_check   -- regeneratable by re-running an assessment
--
-- Tables explicitly preserved (NOT touched here):
--   assessment, completion, app_setting, integration_config, credential,
--   repo_settings, workspace, message, agent_run, ingest_job, audit_log
--
-- After upgrade, the operator must trigger a re-assessment to repopulate
-- findings and posture rows. The release notes for the build that ships
-- this migration repeat this list.
--
-- This migration's destructive license expires at v0.1.0-alpha (ADR-0033 §3).
-- Any future change to `finding` after that tag must be additive.

BEGIN;

-- 1. Drop the legacy tables. Order matters: indexes first, then tables.
DROP INDEX IF EXISTS idx_finding_status;
DROP INDEX IF EXISTS idx_finding_source;
DROP TABLE IF EXISTS finding;

DROP INDEX IF EXISTS idx_posture_check_assessment;
DROP TABLE IF EXISTS posture_check;

-- 2. Recreate the unified finding table per ADR-0027.
CREATE TABLE finding (
    id                  TEXT PRIMARY KEY,
    source_type         TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    type                TEXT NOT NULL DEFAULT 'dependency',
    grade_impact        TEXT NOT NULL DEFAULT 'counts',
    category            TEXT,
    assessment_id       TEXT REFERENCES assessment(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    description         TEXT,
    plain_description   TEXT,
    raw_severity        TEXT,
    normalized_priority TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    likely_owner        TEXT,
    why_this_matters    TEXT,
    asset_id            TEXT,
    asset_label         TEXT,
    raw_payload         TEXT,
    pr_url              TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- 3. Indexes — UNIQUE on (source_type, source_id) is the UPSERT target.
CREATE UNIQUE INDEX uq_finding_source       ON finding(source_type, source_id);
CREATE        INDEX idx_finding_type        ON finding(type);
CREATE        INDEX idx_finding_status      ON finding(status);
CREATE        INDEX idx_finding_assessment  ON finding(assessment_id, type);

COMMIT;
```

### Files created

| File | Purpose |
|------|---------|
| `backend/cliff/db/migrations/011_unified_findings.sql` | the migration above |
| `backend/cliff/assessment/to_findings.py` | four deterministic mappers (signatures below) |
| `backend/tests/db/test_migration_011.py` | starts from a Phase-1-shape DB, runs 011, asserts schema |
| `backend/tests/assessment/test_to_findings.py` | round-trip Trivy/Semgrep/posture fixtures into `FindingCreate` |
| `backend/tests/db/test_repo_finding_upsert.py` | UPSERT preservation (6 preserved cols + representative refreshed cols) |

### Files modified

| File | Change |
|------|--------|
| `backend/cliff/models/finding.py` | add `FindingType = Literal["dependency","code","secret","posture"]` and `FindingGradeImpact = Literal["counts","advisory"]`; add `type`, `grade_impact`, `category`, `assessment_id`, `pr_url` to `FindingCreate`/`FindingUpdate`/`Finding` |
| `backend/cliff/db/repo_finding.py` | rewrite `create_finding` as `INSERT ... ON CONFLICT(source_type, source_id) DO UPDATE` per the preservation table; add `list_findings(type=, grade_impact=, assessment_id=)` filters; add `list_posture_findings(assessment_id)`; add `close_disappeared_findings(source_type, kept_source_ids, assessment_id)` |
| `backend/cliff/api/routes/dashboard.py` | swap posture queries from `list_posture_checks_for_assessment` to `list_posture_findings`; project `(status, pr_url, grade_impact)` → `pass\|fail\|done\|advisory`; vulnerabilities `by_source` filters by `type` |
| `backend/cliff/integrations/normalizer.py` | LLM prompt adds `type` field to output schema (default `dependency`); single rule line per ADR-0027 |
| `backend/cliff/integrations/ingest_worker.py` | thread `type` through from normalizer output to `FindingCreate` |
| `backend/cliff/assessment/engine.py` | after each scanner finishes, persist via `to_findings.*` mappers; after all scanners finish, run the close pass (already shown in pseudocode above) |

### Files deleted

| File | Notes |
|------|-------|
| `backend/cliff/db/dao/posture_check.py` | callers (engine, dashboard route) move to `repo_finding.list_posture_findings` |
| `backend/cliff/models/posture_check.py` | `PostureCheckResult` moves to `backend/cliff/assessment/posture/__init__.py` (it is the in-pipeline DTO, not a DB row) |
| `backend/tests/db/test_posture_check_dao.py` | tests for deleted DAO |

### `to_findings.py` mapper signatures

```python
# backend/cliff/assessment/to_findings.py
from cliff.assessment.scanners.models import TrivyResult, SemgrepResult
from cliff.assessment.posture import PostureCheckResult
from cliff.models.finding import FindingCreate

def from_trivy_vulns(result: TrivyResult, *, assessment_id: str) -> list[FindingCreate]:
    """source_type='trivy', type='dependency', grade_impact='counts'.
    source_id = f'{PkgName}@{InstalledVersion}:{VulnID}'.
    """

def from_trivy_secrets(result: TrivyResult, *, assessment_id: str) -> list[FindingCreate]:
    """source_type='trivy-secret', type='secret', grade_impact='counts'.
    source_id = f'{path}:{startLine}:{RuleID}'.
    """

def from_semgrep(result: SemgrepResult, *, assessment_id: str) -> list[FindingCreate]:
    """source_type='semgrep', type='code', grade_impact='counts'.
    source_id = f'{path}:{startLine}:{check_id}'.
    """

def from_posture(
    results: list[PostureCheckResult], *, repo_url: str, assessment_id: str,
) -> list[FindingCreate]:
    """source_type='cliff-posture', type='posture'.
    Only fail/advisory rows are returned (passes do NOT become finding rows).
    grade_impact='advisory' for advisory checks; otherwise 'counts'.
    category = the posture category (ci_supply_chain | collaborator_hygiene | code_integrity | repo_configuration).
    source_id = f'{repo_url}:{check_name}'.
    """
```

### UPSERT preservation (verbatim from IMPL-0003-p2 §UPSERT)

| Column | On conflict | Reason |
|--------|-------------|--------|
| `id`, `created_at`, `status`, `likely_owner`, `plain_description`, `why_this_matters`, `pr_url` | **Preserve** | row identity / user-set / agent-set / expensive-to-regenerate |
| `title`, `description`, `raw_severity`, `normalized_priority`, `raw_payload`, `type`, `grade_impact`, `category`, `assessment_id`, `asset_id`, `asset_label`, `updated_at` | **Refresh** | scanner truth |

SQLite UPSERT shape:

```sql
INSERT INTO finding (id, source_type, source_id, type, grade_impact, category,
                     assessment_id, title, description, plain_description,
                     raw_severity, normalized_priority, status, likely_owner,
                     why_this_matters, asset_id, asset_label, raw_payload, pr_url,
                     created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(source_type, source_id) DO UPDATE SET
    title               = excluded.title,
    description         = excluded.description,
    raw_severity        = excluded.raw_severity,
    normalized_priority = excluded.normalized_priority,
    raw_payload         = excluded.raw_payload,
    type                = excluded.type,
    grade_impact        = excluded.grade_impact,
    category            = excluded.category,
    assessment_id       = excluded.assessment_id,
    asset_id            = excluded.asset_id,
    asset_label         = excluded.asset_label,
    updated_at          = excluded.updated_at
;
```

### Stale-close rule (verbatim from ADR-0027 §7 + IMPL-0003-p2)

`close_disappeared_findings(source_type, kept_source_ids: set[str], assessment_id: str)`:

1. **First-run guard** — if no prior `assessment` row exists for the same `repo_url`, return early (nothing to close).
2. Select rows from `finding` where `source_type = ?` AND `source_id NOT IN ({kept_source_ids})` AND `status NOT IN ('closed', 'remediated', 'validated')`.
3. For each such row, set `status = 'closed'` and append `{event: 'auto_closed', reason: 'not seen in scan', assessment_id, ts}` to `raw_payload.system_notes`.
4. Scope by `source_type` (NOT `type`). Trivy never closes Snyk/Wiz findings.
5. The caller (engine) only invokes this for `source_type`s whose scanner actually ran (i.e., not `skipped`).

### Phase 2 acceptance criteria

- `grep -r "from cliff.db.dao.posture_check\|from cliff.models.posture_check" backend/` → zero hits
- `posture_check` table does not exist after migration 011 (`test_migration_011`)
- All 4 mappers have round-trip tests
- UPSERT preservation covers all 6 preserved columns and 4 representative refreshed columns
- All ADR-0027 stale-close scenarios covered (3 tests below)
- PR-A's `test_dashboard_v2_payload.py` still passes
- `cd backend && uv run pytest -v` → green

---

## Phase 3 — Frontend pixel-fidelity rebuild

**Goal.** Every PRD-0003 surface matches its mockup in `frontend/mockups/claude-design/surfaces/*.jsx`. The user-visible product moves to v0.2.

### New components

| File | One-line summary |
|------|------------------|
| `frontend/src/components/dashboard/ToolPillBar.tsx` | Tool-identity pills with `pending\|active\|done\|skipped` states; `result?` drives the "Trivy 0.52 · 7 findings" tail; size variants `sm\|md` |
| `frontend/src/components/dashboard/CategoryHeader.tsx` | Eyebrow + done/total numerals + 80px progress rail |
| `frontend/src/components/dashboard/PostureCategoryGroup.tsx` | `<CategoryHeader>` + `<ul>` of `PostureCheckItem` rows grouped by category |
| `frontend/src/components/dashboard/ScannedByLine.tsx` | "Scanned by" eyebrow + `ToolPillBar` (size `sm`, all `done`, with results) |
| `frontend/src/components/dashboard/AssessmentSummary.tsx` | Surface 3 — three cards (vulns / posture / quick wins) + grade preview + CTA |
| `frontend/src/components/PillButton.tsx` | Primary / ghost / surface variants; size + icon support |
| `frontend/src/components/dashboard/__tests__/ToolPillBar.test.tsx` | tests below |
| `frontend/src/components/dashboard/__tests__/PostureCategoryGroup.test.tsx` | tests below |
| `frontend/src/components/dashboard/__tests__/AssessmentSummary.test.tsx` | tests below |
| `frontend/src/components/__tests__/PillButton.test.tsx` | tests below |

### Pages and existing components modified

| File | Change |
|------|--------|
| `frontend/src/pages/DashboardPage.tsx` | Hero: three-column flex (`GradeRing` 120 + narrative + last-assessed/Re-assess); inset `ScannedByLine` row; two-column body (vulns 380px + posture 1fr using `PostureCategoryGroup`×4); narrative copy derived from `criteria.met / 10` + count of fixable failing posture checks; assessment-complete interstitial gate (`summary_seen_at == null && status === 'complete'` → `<AssessmentSummary>` instead of report card; CTA fires `markSummarySeen(id)`) |
| `frontend/src/components/dashboard/AssessmentProgressList.tsx` | Replace hardcoded steps with `dashboardData.steps[]`; render `ToolPillBar` from `dashboardData.tools[]`; active step expands into `bg-primary-container/30` card with progress bar; pending steps show optional `hint` chip; render Previous-assessment sub-card |
| `frontend/src/components/dashboard/CompletionProgressCard.tsx` | Pill meter → continuous progress bar with 11 ticks (0..10); 2-column criteria chip grid using labeled `criteria[]`; footer copy updated |
| `frontend/src/components/dashboard/PostureCheckItem.tsx` | Four explicit state components driven by `state` (`pass`, `fail`, `done`, `advisory`); `done` renders `Draft PR ↗` link to `pr_url`; `fail` renders generator CTA when `fixable_by` is set |
| `frontend/src/components/dashboard/GradeRing.tsx` | Confirm size variants `72\|96\|120\|192` + `.grade-ring` class with `--p` |
| `frontend/src/pages/onboarding/StartAssessment.tsx` | 3 → 4 step previews with explicit time estimates (10s · 60s · 30s · 60s); "Powered by" `ToolPillBar` row |
| `frontend/src/components/CompletionCelebration/ShareableSummaryCard.tsx` | "5 criteria met" → "10 criteria met"; new `Scanned by:` line above wordmark |
| `frontend/src/api/dashboard.ts` | Add `markSummarySeen(assessmentId)` mutation; add `excludeAssessmentId?` query param to `useDashboard` |

### Existing tests updated

- `frontend/src/components/dashboard/__tests__/CompletionProgressCard.test.tsx` — 5 → 10 criteria, 11 ticks
- `frontend/src/components/dashboard/__tests__/AssessmentProgressList.test.tsx` — drives off `tools[]` + `steps[]`
- `frontend/src/components/dashboard/__tests__/SeverityChip.test.tsx` — already covers medium=warning regression; no change needed

---

## Final — Manual verification gate

`docs/architecture/plans/IMPL-0003-p2-verification-report.md` is committed before flagging the PR ready. Contents (verbatim from IMPL-0003-p2 §Final):

- Git SHA of HEAD of `feat/prd-0003-p2-complete`
- OS / browser / screen size used
- Embedded screenshots for each checklist item below
- Tail of `cd backend && uv run pytest -v` and `cd frontend && npm test`
- One-paragraph summary: "Ready for CEO walkthrough" or list of remaining issues

Walkthrough surfaces (each: visual confirm + screenshot + side-by-side with mockup):

1. Onboarding step 3 vs `surfaces/onboarding-step3.jsx`
2. Assessment progress vs `surfaces/assessment-progress.jsx`
3. Assessment-complete interstitial vs `surfaces/assessment-complete.jsx` (variation A); reload-safe (re-clicks don't re-show)
4. Report-card hero vs `surfaces/report-card.jsx`
5. Posture card — four category groups, mix of pass/fail/done/advisory, ≥1 done with real `pr_url`, ≥1 fail with generator CTA
6. Completion progress vs `surfaces/completion-progress.jsx` (11 ticks, 10 chips)
7. Severity colors — medium = warning amber (NOT green), critical/high red, low neutral, code indigo
8. Share card vs `surfaces/share-card.jsx` — "10 criteria met" + "Scanned by" line
9. Reduced motion — spinners + pulses stop with OS toggle
10. Keyboard navigation — every interactive element has a visible focus ring

The PR cannot merge until this file is committed.

---

## Test plan — exact list (file path → test names)

### Phase 1 — Engine cutover (`backend/`)

`tests/assessment/test_engine.py` (full rewrite):

- `test_engine_step_reporting_emits_six_keys_in_order`
- `test_engine_tools_emission_three_pills_pending_active_done`
- `test_engine_trivy_failure_is_fatal`
- `test_engine_semgrep_failure_is_graceful_skipped_state`
- `test_engine_posture_per_check_unknown_does_not_abort`
- `test_engine_subprocess_env_whitelist_preserved`
- `test_engine_returns_assessment_result_with_tools_payload`
- `test_engine_clones_via_repo_cloner_and_uses_path_for_scanners`
- `test_engine_invokes_runner_with_concurrency_one_for_subprocess_isolation`
- `test_engine_grade_derivation_unchanged_from_pra`

`tests/api/test_integration_engine.py` (update):

- `test_assessment_run_invokes_run_assessment_not_legacy`
- `test_assessment_status_streams_steps_and_tools`

### Phase 2 — Unified findings (`backend/`)

`tests/db/test_migration_011.py` (new):

- `test_migration_011_drops_posture_check_table`
- `test_migration_011_finding_table_has_unified_columns`
- `test_migration_011_creates_unique_index_on_source_type_source_id`
- `test_migration_011_destroys_legacy_finding_rows` (data loss expected per ADR-0033)

`tests/assessment/test_to_findings.py` (new):

- `test_from_trivy_vulns_round_trip_fixture`
- `test_from_trivy_vulns_source_id_format`
- `test_from_trivy_secrets_round_trip_fixture`
- `test_from_trivy_secrets_source_id_format`
- `test_from_semgrep_round_trip_fixture`
- `test_from_semgrep_source_id_format`
- `test_from_posture_emits_only_fail_and_advisory`
- `test_from_posture_source_id_uses_repo_url_check_name`
- `test_from_posture_grade_impact_advisory_for_advisory_checks`
- `test_from_posture_category_threaded_through`

`tests/db/test_repo_finding_upsert.py` (new):

- `test_upsert_preserves_id_and_created_at_on_conflict`
- `test_upsert_preserves_status_when_user_triaged`
- `test_upsert_preserves_likely_owner_plain_description_why_this_matters`
- `test_upsert_preserves_pr_url_set_by_agent`
- `test_upsert_refreshes_title_description_raw_severity_normalized_priority`
- `test_upsert_refreshes_raw_payload_type_grade_impact_category`
- `test_upsert_refreshes_assessment_id_and_updated_at`

`tests/assessment/test_engine_close_pass.py` (new):

- `test_engine_closes_disappeared_findings_secret_only`  *(scan 1: dep+secret, scan 2: dep only → secret rows closed)*
- `test_engine_skip_does_not_close_findings`
- `test_trivy_rescan_does_not_close_external_snyk_findings`
- `test_first_assessment_run_skips_close_pass`
- `test_close_pass_appends_system_note_to_raw_payload`

`tests/api/test_dashboard_v2_payload.py` (PR-A — re-run, must stay green):

- `test_dashboard_grouped_posture_four_state` *(now reads from unified table)*
- `test_dashboard_omits_legacy_scanner_versions`
- 8 other PR-A contract tests, unchanged

`tests/integrations/test_normalizer_type_field.py` (new):

- `test_normalizer_emits_type_field_with_default_dependency`
- `test_normalizer_emits_type_secret_for_credential_payloads`
- `test_normalizer_emits_type_code_for_sast_payloads`
- `test_normalizer_emits_type_posture_for_hygiene_payloads`

### Phase 3 — Frontend (`frontend/`)

`src/components/dashboard/__tests__/ToolPillBar.test.tsx` (new):

- `renders_three_pills_for_trivy_semgrep_posture`
- `pending_state_shows_no_result_tail`
- `active_state_uses_animate_pulse_subtle`
- `done_state_renders_result_text`
- `skipped_state_visually_distinct_and_no_result`
- `size_sm_compresses_padding_and_font_size`

`src/components/dashboard/__tests__/PostureCategoryGroup.test.tsx` (new):

- `renders_category_header_with_done_total`
- `renders_pass_fail_done_advisory_rows_in_correct_states`
- `advisory_rows_excluded_from_progress_count`
- `progress_rail_width_matches_done_over_total`

`src/components/dashboard/__tests__/AssessmentSummary.test.tsx` (new):

- `renders_three_summary_cards_with_counts`
- `renders_grade_preview_below_cards`
- `cta_fires_on_view_report_card`
- `accessibility_focus_ring_on_cta`

`src/components/__tests__/PillButton.test.tsx` (new):

- `primary_variant_applies_correct_tokens`
- `ghost_variant_applies_correct_tokens`
- `surface_variant_applies_correct_tokens`
- `disabled_state_blocks_click`
- `focus_visible_ring_present`

`src/components/dashboard/__tests__/PostureCheckItem.test.tsx` (rewrite):

- `pass_state_renders_check_circle_in_tertiary`
- `fail_state_renders_card_style_row_with_cancel_icon`
- `fail_state_with_fixable_by_renders_generator_cta`
- `done_state_renders_check_circle_plus_draft_pr_link_to_pr_url`
- `advisory_state_renders_info_icon_and_advisory_chip`

`src/components/dashboard/__tests__/CompletionProgressCard.test.tsx` (update):

- `renders_eleven_ticks_zero_through_ten`
- `renders_two_column_chip_grid_with_labels`
- `met_chip_visually_distinct_from_unmet`

`src/components/dashboard/__tests__/AssessmentProgressList.test.tsx` (update):

- `renders_steps_from_api_not_hardcoded`
- `renders_tool_pill_bar_from_tools_array`
- `active_step_expands_to_card_with_progress_bar`
- `pending_step_renders_hint_chip_when_provided`
- `previous_assessment_sub_card_visible_when_query_returns_one`

`src/pages/__tests__/DashboardPage.test.tsx` (update):

- `interstitial_renders_when_summary_seen_at_is_null_and_status_complete`
- `interstitial_does_not_render_when_summary_seen_at_set`
- `cta_calls_mark_summary_seen_and_falls_through`
- `hero_renders_grade_ring_narrative_and_re_assess_button`
- `scanned_by_line_renders_three_tool_pills_with_results`

`src/api/__tests__/dashboard.test.tsx` (update):

- `mark_summary_seen_posts_to_correct_endpoint`
- `use_dashboard_passes_exclude_assessment_id`

---

## Pixel-fidelity verification methodology

For each surface in `frontend/mockups/claude-design/surfaces/*.jsx`:

1. **Open both side-by-side at the same viewport.** Mockup HTML lives at `frontend/mockups/claude-design/PRD-0003 design.html` (open in Chrome at 1440×900). Live app at `http://localhost:5173/<route>` in a second window at the same size.
2. **Compare in this order** — layout (column widths, gap sizes), spacing (page padding `px-8 py-7`, card gap `gap-2/3/5`), typography (Manrope 800 titles, Inter 400 body, JetBrains Mono numerals, tabular-nums), color (background levels 0/1/2, primary `#4d44e3`, warning amber, ghost-border opacity), and state (active pulse, hover lift, focus ring).
3. **Capture a screenshot** of each surface at completion. Annotate any deliberate deviation with a one-line reason; silent drift is unacceptable.
4. **Acceptable diffs** — antialiasing, system-font subpixel jitter, scrollbar style. **Unacceptable** — layout shift, color drift, missing states, wrong type sizes, missing focus ring, missing reduced-motion guard.
5. **Reduced-motion + keyboard sweep** — toggle the OS reduced-motion setting; tab through every interactive element on every surface to confirm focus rings.

The 7 surface comparisons (onboarding step 3, assessment progress, assessment-complete, report card, posture card, completion progress, share card) attach as screenshots to `IMPL-0003-p2-verification-report.md`.

---

## Commit cadence (estimated)

The branch will end with roughly 15–18 commits. One commit per logical chunk so the diff is reviewable:

**Phase 1 — engine cutover (5 commits):**
1. `feat(engine): introduce run_assessment(repo_url, ...) skeleton with on_step/on_tool callbacks`
2. `feat(engine): wire SubprocessScannerRunner.run_trivy + run_semgrep into run_assessment`
3. `refactor(api): /assessment/run + /assessment/status switch to run_assessment`
4. `chore(engine): delete parsers/, osv_client, ghsa_client, production_engine and their tests`
5. `test(engine): rewrite test_engine.py against the new pipeline`

**Phase 2 — unified findings (6 commits):**
6. `feat(db): migration 011 drops legacy finding + posture_check, recreates unified finding (ADR-0033)`
7. `feat(models): add type/grade_impact/category/assessment_id/pr_url to Finding models`
8. `feat(db): create_finding becomes UPSERT on (source_type, source_id) with preservation rules`
9. `feat(assessment): add to_findings.py mappers for trivy/trivy-secret/semgrep/posture`
10. `feat(engine): persist findings via mappers, run stale-close pass scoped by source_type`
11. `refactor(api): dashboard route reads unified finding table; delete posture_check DAO + model`

**Phase 3 — frontend rebuild (5 commits):**
12. `feat(ui): add ToolPillBar, CategoryHeader, PostureCategoryGroup, ScannedByLine, PillButton`
13. `feat(ui): rebuild PostureCheckItem with four explicit states (pass/fail/done/advisory)`
14. `feat(ui): rebuild DashboardPage hero + interstitial gate via summary_seen_at`
15. `feat(ui): AssessmentProgressList drives off tools[] + steps[]; add Previous-assessment sub-card`
16. `feat(ui): CompletionProgressCard 11-tick bar + 10-chip grid; StartAssessment 4 steps + powered-by`

**Final (1–2 commits):**
17. `docs: IMPL-0003-p2 verification report (screenshots + test tail)`
18. (optional) `docs(adr): flip ADR-0027/0028/0029/0032/0033 to Accepted` — done as part of v0.1.0-alpha tag commit, not required in this PR

Each phase boundary runs `cd backend && uv run pytest -v && uv run ruff check cliff/ tests/` and `cd frontend && npm test && npm run build` before advancing.

---

## Open questions — resolved 2026-04-26 (CEO)

The three Step-1 questions were answered before execution. Resolutions are folded into the design above and recorded here for the audit trail.

### Q1 — RESOLVED: option (a). Persist all 15 posture results as `finding` rows.

CEO directive: "the finding table should contain all findings we've had — history + in progress + todo. We don't need backward compatibility, go with (a)." This aligns the dashboard count with ADR-0032's literal SQL and gives the Findings page a complete picture once it grows to filter on `type='posture'`.

**Implementation consequences (all already reflected in the design above):**

1. `from_posture` returns **all 15** `PostureCheckResult` rows, not just fail/advisory. ADR-0027 §4 ("we do not pollute the findings backlog with 'a thing that's fine'") is consciously overridden for v0.2; the conflict is noted in the migration 011 leading comment so a future maintainer sees the deliberate choice.
2. `models/finding.py` adds `'passed'` to `FindingStatus`:
   ```python
   FindingStatus = Literal[
       "new", "triaged", "in_progress", "remediated", "validated",
       "closed", "exception", "passed",   # NEW: scanner-reports-pass for posture
   ]
   ```
3. **Type-conditional UPSERT rule.** For `type='posture'`, `status` is **REFRESHED** from scanner output on conflict (the scanner is the source of truth for whether a posture check passes). For all other types, `status` is **PRESERVED** per the original ADR-0027 rule (user lifecycle state must survive a rescan). This is a single conditional inside `create_finding` and is covered by an explicit test (`test_upsert_refreshes_status_for_posture_only`).
4. Mapper-side status assignment in `from_posture`:
   - `PostureCheckResult.status == "pass"` → `FindingCreate(status="passed", grade_impact="counts")`
   - `PostureCheckResult.status == "fail"` → `FindingCreate(status="new",    grade_impact="counts")`
   - `PostureCheckResult.status == "advisory"` → `FindingCreate(status="new", grade_impact="advisory")`
   - `PostureCheckResult.status == "unknown"` → **no row emitted** (per ADR-0027 §7: absence of signal is not evidence of fix; ADR-0032 four-state vocab has no `unknown`).
5. **Stale-close pass for posture is removed.** Every scan emits a row for every check (15-of-15), so there is no "disappearance" to close. The stale-close pass still runs for `trivy`, `trivy-secret`, and `semgrep` (their `source_id`s vary per scan). This simplifies posture lifecycle: status is fully determined by the latest scan + the agent's `pr_url`.
6. **Dashboard four-state projection** (verbatim — implements ADR-0032 §2 against the unified table):
   - `status='passed'` AND `pr_url IS NULL`         → `'pass'`
   - `status='passed'` AND `pr_url IS NOT NULL`     → `'done'` (agent fixed it, scanner now reports pass)
   - `grade_impact='advisory'` (regardless of status) → `'advisory'`
   - everything else (status in `new\|triaged\|in_progress\|remediated`, grade_impact='counts') → `'fail'`
   - The "agent submitted a PR but the rescan still shows fail" case is intentionally rendered as `'fail'` — the row stays actionable until the next scan confirms `'passed'`.
7. **Posture pass count on the wire** is now `count(finding) WHERE type='posture' AND status='passed' AND assessment_id=X` — exactly ADR-0032 §1's literal SQL. The engine still also emits the count into `tools_json` (so the running-state UI has it before persistence completes).
8. **Test additions** (already in the test list):
   - `test_from_posture_emits_all_fifteen_results_including_passes`
   - `test_from_posture_skips_unknown_status`
   - `test_upsert_refreshes_status_for_posture_only`
   - `test_dashboard_done_projection_status_passed_with_pr_url`

### Q2 — RESOLVED. Destructive scope stays at `finding` + `posture_check` only.

CEO directive: `ingest_job`, `agent_run`, and chat history (`message`) are still in active use and must be preserved. Migration 011 drops only `finding` and `posture_check`. The migration leading comment is updated to make this explicit. ADR-0033's broader authorized scope remains valid for *future* migrations but is not exercised here.

### Q3 — RESOLVED. Synthetic Snyk seed in `test_trivy_rescan_does_not_close_external_findings` is fine.

The test inserts `FindingCreate(source_type='snyk', source_id='snyk:CVE-...', type='dependency', ...)` directly via `create_finding` before the Trivy scan, then asserts the row survives. No real Snyk adapter required.

---

Plan updated, ready for Step 2 — create `feat/prd-0003-p2-complete` from `main`, commit this plan to `docs/architecture/plans/IMPL-0003-p2-execution-plan.md`, then execute end-to-end without pausing between phases.
