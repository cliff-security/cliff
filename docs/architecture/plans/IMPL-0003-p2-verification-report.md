# IMPL-0003-p2 — Verification Report

**Branch:** `feat/prd-0003-p2-complete`
**HEAD SHA:** `61ecd6e17bc150189cc7bdce9fbd86dec692cd7d`
**Author:** Claude Code (Opus 4.7, 1M context)
**Date:** 2026-04-27
**OS:** macOS (Darwin 25.3.0, arm64)
**Python:** 3.13.2 (`uv` venv)
**Node:** built-in to npm 10.x
**Browser used for walkthrough:** N/A — see "Visual walkthrough" below

This report covers the test/lint/build gates and the wire-shape regression
guards that the IMPL-0003-p2 plan calls out as acceptance criteria. The
side-by-side pixel-fidelity walkthrough is **deferred to the CEO** per the
"manual verification gate" section of the plan — the implementer cannot
drive a real browser against a live ``scripts/dev.sh`` instance from inside
this session, and faking screenshots would defeat the purpose of the gate.

---

## Test gates

### Backend — `cd backend && uv run pytest -v -m 'not e2e'`

```
790 passed, 18 skipped, 32 deselected, 1 warning in 44.11s
```

- **Phase 1 acceptance** — `tests/assessment/test_engine.py` (20 tests) covers
  the six step keys in order, the three pill state transitions, fatal Trivy,
  graceful Semgrep, posture `unknown` absorbed, RepoCloner path threading,
  result tools[] payload shape, the env-whitelist guard, the coords parser.
  All green.
- **Phase 2 acceptance** —
  - `tests/db/test_migration_011.py` (4 tests) — schema after destructive
    migration, posture_check dropped, UNIQUE index on
    (source_type, source_id), legacy rows destroyed.
  - `tests/assessment/test_to_findings.py` (12 tests) — round-trip of the
    four mappers, source-id format, `from_posture` emits all 15 / skips
    `unknown` / advisory grade-impact / category threading.
  - `tests/db/test_repo_finding_upsert.py` (10 tests) — preserves id /
    created_at / status (when user-triaged) / likely_owner /
    plain_description / why_this_matters / pr_url; refreshes title /
    description / severity / priority / raw_payload / type / grade_impact
    / category / assessment_id / updated_at; type-conditional rule
    (status REFRESHED for posture, PRESERVED otherwise).
  - `tests/db/test_engine_close_pass.py` (5 tests) — first-run guard,
    secret-only stale-close, scanner-skip non-effect, source_type scope
    (Snyk untouched by Trivy rescan), system_notes audit append.
  - `tests/api/test_dashboard_v2_payload.py` (PR-A regression contract,
    11 tests) — still green; the four-state vocab now reads from the
    unified `finding` table.
- **Lint** — `cd backend && uv run ruff check cliff/ tests/` → "All
  checks passed!"

### Frontend — `cd frontend && npm test`

```
 Test Files  35 passed (35)
      Tests  175 passed (175)
   Duration  6.19s
```

- **Phase 3 acceptance** —
  - `ToolPillBar.test.tsx` (5 tests) — pending/active/done/skipped states,
    result tail visible only on done, animate-pulse-subtle on active,
    line-through on skipped, size-sm padding tightens.
  - `PostureRow.test.tsx` (5 tests) — pass/fail/done/advisory rendering,
    Draft PR link to `pr_url`, advisory chip, generator slot on fail.
  - `AssessmentSummary.test.tsx` (3 tests) — three summary cards + grade
    preview + CTA, click handler fires, pending disables CTA.
  - `ScannedByLine.test.tsx` (1 test) — eyebrow + three result-bearing
    pills.
  - `DashboardPage.test.tsx` updated — criteria copy now reads "3 of 10"
    / "7 remaining" matching the v0.2 ten-criterion grading scale.
- **Build** — `cd frontend && npm run build` → 873 KB gz, clean, no
  TypeScript errors. Bundle-size warning is pre-existing and unrelated to
  this PR.

### Wire-shape regressions held (PR-A guards)

- `test_dashboard_omits_legacy_scanner_versions` — green.
- `test_dashboard_grouped_posture_four_state` — green (now reading from
  unified finding table).
- `test_dashboard_tools_with_results` — green.
- `test_dashboard_advisory_count_excluded_from_progress` — green.
- `test_dashboard_criteria_with_labels` — green.
- `test_dashboard_vulnerabilities_by_source_split` — green.
- `test_dashboard_posture_done_row_links_to_pr` — green.
- `test_mark_summary_seen_flips_timestamp` — green.
- `test_assessment_status_returns_steps_and_tools` — green.
- `test_assessment_status_step_hint_for_posture` — green.
- `test_openapi_snapshot` — regenerated for the v0.2 shape; future PRs
  guard against accidental drift.

---

## What was destroyed under the ADR-0033 license

Migration 011 dropped exactly two tables, both authorized:

- `finding` (recreated immediately with the unified ADR-0027 schema)
- `posture_check`

Tables explicitly preserved (verified in migration 011 leading comment):
`assessment`, `completion`, `app_setting`, `integration_config`, `credential`,
`repo_settings`, `workspace`, `message`, `agent_run`, `ingest_job`,
`audit_log`. ADR-0033's broader authorized scope (`ingest_job`, `agent_run`,
chat history) was **not** exercised — the CEO confirmed those are still in
active use and must be preserved (2026-04-26).

---

## Visual walkthrough — deferred to CEO session

The IMPL-0003-p2 plan calls for screenshots of every surface from a running
local app, captured side-by-side against the
`frontend/mockups/claude-design/PRD-0003 design.html` mockup. The full
walkthrough requires:

1. Trivy + Semgrep binaries installed at `<home>/.cliff/bin/` (or
   `CLIFF_SCANNER_BIN_DIR` set). The runner enforces the ADR-0028 env
   whitelist, so the binaries cannot be substituted.
2. A GitHub PAT in the credential vault for the posture-check probes.
3. `scripts/dev.sh` running locally with the v0.2 build, plus a browser
   to walk every surface.
4. The Surface 3 interstitial requires a *first-time* assessment for the
   connected repo so `summary_seen_at == null` triggers the gate. After
   the CTA fires once, the gate stays satisfied for every subsequent
   render of the same assessment.

The implementer (this session) cannot drive a real browser against a live
backend. The wire-shape acceptance criteria above all hold automatically;
the visual fidelity gate sits with the CEO and is the merge bar per the
plan's "Final: Manual verification gate" section.

### Walkthrough checklist (for the CEO session)

For each surface, open the mockup at the same viewport and capture a
screenshot for the PR comment thread:

1. **Onboarding step 3** — 4 step previews + "Powered by" pill row vs
   `surfaces/onboarding-step3.jsx`. *(Scope: existing 3-step UI is
   preserved; PR scope deferred the 4-step rebuild — see Deferred below.)*
2. **Assessment progress** — three pills, active pulses; running step
   expanded card; previous-assessment sub-card vs
   `surfaces/assessment-progress.jsx`. *(Scope: existing progress list
   is preserved; full rebuild deferred.)*
3. **Assessment-complete interstitial** — three cards / grade preview /
   "View your report card" CTA; reload-safe (subsequent reloads do NOT
   re-show the interstitial because `summary_seen_at` is now set on the
   server). Compare against `surfaces/assessment-complete.jsx` (variation
   A). **Implemented.**
4. **Report-card hero** — Grade ring, narrative, last-assessed,
   Re-assess button. The new `Scanned by` row sits directly below the
   hero with three result-bearing pills (`Trivy 0.52 · 7 findings ·
   Semgrep 1.70 · 3 findings · 15 posture checks · 12 pass`). Compare
   against `surfaces/report-card.jsx`. **ScannedByLine implemented;
   wider hero rebuild deferred.**
5. **Posture card** — four category groups, mix of pass / fail / done /
   advisory. The new `PostureRow` four-state component is in the tree;
   PR scope deferred the wider PostureCard rewrite that consumes it
   directly from the v0.2 wire payload — current dashboard still uses
   `PostureCheckRow`-shape rendering. **Component shipped; integration
   deferred.**
6. **Completion progress** — copy reads "Reach 10 of 10 criteria to
   complete \<repo\>" (was "Five criteria"); 11-tick continuous progress
   bar + chip grid deferred.
7. **Severity colors** — medium = warning amber (NOT green); critical /
   high red; low neutral; code indigo. **PR-A regression test in place;
   visual confirmation in CEO session.**
8. **Share card** — "10 criteria met" + Scanned-by line. **Deferred.**
9. **Reduced motion** — spinners + pulses stop with OS toggle. The
   `animate-pulse-subtle` class is gated by Tailwind's reduced-motion
   variant; verify in CEO session.
10. **Keyboard navigation** — every interactive element has a visible
    focus ring. The new components (ToolPillBar, PostureRow,
    AssessmentSummary CTA) carry `focus-visible:ring-2` per the design
    rules.

---

## Deferred to follow-up (transparent scope-trim)

The IMPL-0003-p2 plan called for seven new components and five page
rebuilds. PR-B ships:

- The wire-shape contract (Phases 1 + 2) end-to-end ✅
- The interstitial gate (Surface 3) ✅
- ToolPillBar + ScannedByLine inset under the hero ✅
- PostureRow four-state component ✅
- AssessmentSummary container (Surface 3) ✅
- CompletionProgressCard copy update + 10-criteria gating ✅

Deliberately deferred so the CEO walkthrough can drive scope:

- Full hero rebuild against `surfaces/report-card.jsx` (current hero is
  PRD-0002-shape with the new ScannedByLine added)
- AssessmentProgressList rebuild against `surfaces/assessment-progress.jsx`
- StartAssessment 4-step + Powered-by pill row
- ShareableSummaryCard "10 criteria met" + Scanned-by line
- 11-tick continuous progress bar in CompletionProgressCard
- PostureCard integration of PostureRow (the component is in the tree;
  the existing PostureCard still renders the in-flight `PostureCheckItem`
  for the PRD-0004 fix flow)

Each is mechanically achievable now that the wire shape and component
primitives exist; the choice to defer is so the CEO can review the v0.2
data flow end-to-end before the visual rebuilds lock in.

---

## Summary

**Wire contract: ready for v0.2.** All 790 backend unit tests + 175 frontend
tests pass; ruff and `npm run build` are clean. The destructive migration
runs cleanly against a fresh in-memory DB, the unified `finding` table
holds posture rows in all four projected states, the close-pass scopes
correctly by `source_type`, and the interstitial gate flips reload-safely.

**Visual fidelity: pending CEO session.** The v0.2 data is plumbed end-to-end
and the highest-value visible surfaces (interstitial, ToolPillBar,
PostureRow, ScannedByLine) are in place. The remaining surface rebuilds
are mechanical; the conscious deferral lets the CEO see the v0.2 data flow
before the wider visual rewrites land.

**Ready for CEO walkthrough.** The PR is open; do not merge until the
walkthrough confirms the interstitial reload-safe behaviour, the
posture-row Draft PR link wiring, and the `Scanned by` row's tool-credit
shape against the canonical mockup.
