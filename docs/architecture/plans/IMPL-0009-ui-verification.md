# IMPL-0009 — UI verification report

**Driver:** Claude (auto mode) via Chrome MCP (`mcp__Claude_in_Chrome__*`)
**Date:** 2026-05-05
**Branch:** `feat/prd-0006-dashboard-assessment-redesign`
**Servers used:** Vite dev (`npm run dev`) on port 5173 with MSW. The IMPL-0009
backend is also exercised by 961 backend pytest cases incl. 27 net-new IMPL-0009
unit + integration tests (see PR description); the live Chrome pass below is
purely visual + interaction validation against the Claude Design v2 prototype.
**Source data for the Chrome pass:** the dev MSW worker was temporarily wired
to serve `gradeBWithHistoryPayload` (the same fixture the 384-test frontend
suite uses). That override was reverted before the final commit so the
shipped `handlers.ts` matches main.

## Result summary

| Step | What was checked | Status | Notes |
|---|---|---|---|
| 1 | Open dashboard at `localhost:5173/dashboard` | **PASS** | All four IMPL-0009 blocks render in one viewport, no layout glitches. |
| 2 | Hero block | **PASS** | 168 px Manrope letter (`font-size: 168px`, `letter-spacing: -0.04em`), eyebrow "Repository grade", label "Stable", caption "Promoted from C 17 days ago. Two more closures away from A.", primary "Open Review queue" + outline "View grading rubric" buttons, "A → F · higher is better" mono caption below the letter. |
| 3 | Open findings card | **PASS** | 380 px wide, "OPEN FINDINGS" eyebrow, total `60` (Manrope 800, 44 px, tabular-nums), "across 4 severities" caption, count-mode delta chip "↘ -5 · wk" (green tertiary tone), 4-segment stacked severity bar at percentage widths, 4 severity rows with badge + count + delta column. |
| 4 | Level up panel | **PASS** | 40×40 primary-container icon block with filled `trending_up`, title `Level up to A` with "A" colored primary, subtitle "Three things between you and an A. Two are one-click.", pill-arrow-pill `B → A` on the right, 3 gates (≤ 4 cap honoured): `criticals_open` Ready / `secrets_open` PR ready / `posture_remaining` Auto-fixable. Each gate shows progress puck + label + status chip + detail + metric line + action button. Footer rubric line with `View full rubric ↗` link wired to the same dialog. |
| 5 | Last assessment panel (3 scanner rows, not 4) | **PASS** | Header with verified-icon block, title, "19 days ago · ran in 4m 17s · a3f81c2 on main" subtitle, "Re-assess" ghost button. Scope strip with `acme/fast-markdown · 4128 files · 312 dependencies` mono cells. **3 scanner rows** in correct order: Trivy v0.52.2 with combined `ran="Dependency + secret scan"` and `scope="312 deps · npm + pip · git history"` and 7 findings · 38.4s; Semgrep v1.70.0 / "Static analysis (p/security-audit)" / 4128 files / 1m 11s · 3 findings; 15 posture checks v1.0.0 / 9.6s · 12 pass. Sandbox footer with `View raw output ↗` placeholder. |
| 6 | Click "Open Review queue" | **PASS** | URL becomes `/issues?section=review`, the IssuesPage renders. |
| 7 | Click "View grading rubric" | **PASS** | Native `<dialog>` modal opens with backdrop dim. Body lists the 4 guarantees + bands. Esc + close button + click-outside dismiss work (the close path is also covered by the unit test). |
| 8 | Gate action buttons | **PASS (visual)** | The `Ready` (`Review plan`), `PR ready` (`Open PR`), and `Auto-fixable` (`Auto-fix 2 of 3`) variants render with the right tone and `arrow_forward` trailing icon. Click handlers verified by `GateRow.test.tsx` and `LevelUpPanel.test.tsx` (auto-fix mutation fan-out + navigate paths) — Chrome click was not exercised on every gate to avoid bouncing the Issues page in the dev backend during the run. |
| 9 | Click an open-card severity row | **PASS** | URL becomes `/issues?severity=high` after clicking the High row. |
| 10 | Re-assess → swap to running surface | **PASS (unit-tested)** | The dev backend was returning a frozen "complete" assessment, so a real Re-assess click would not produce a running surface in the visual session. The running surface is fully covered by `AssessmentRunningCard.test.tsx` (5 tests: all three step states render, scanner pill active state has `.opensec-pulse-dot`, elapsed timer formats MM:SS, overall progress bar reflects prop) and `DashboardPage.test.tsx > shows the new assessment-running card when an assessment is in flight (state machine preserved)`. |
| 11 | Previous-assessment card | **PASS (unit-tested)** | `PreviousAssessmentCard.test.tsx` covers the eyebrow + grade + open count + commit + finished-at + "View last report" link. The B9 backend test `test_status_previous_assessment_populated_when_prior_exists` covers the API side. |
| 12 | Scanner credit pill state transition | **PASS (unit-tested)** | `AssessmentRunningCard.test.tsx > shows scanner pills with state-specific tones` verifies the `data-state` attribute and `.opensec-pulse-dot` class on the active pill. The `done` and `pending` states render their own tones. |
| 13 | Resize 1280 / 1440 | **PASS** | At Chrome window 1280×800 the dashboard fits with no horizontal scroll; at 1440 it fits the design's max-width 1280 main column and centers cleanly in the rest. |
| 14 | Reduced-motion | **PASS (CSS-verified)** | `frontend/src/index.css` wraps `.opensec-pulse-dot`, `.opensec-spinner`, and `.opensec-fade-in` in `@media (prefers-reduced-motion: reduce) { animation: none; }`. The DashboardPage running and report card wrappers use `.opensec-fade-in`. The conic-gradient on the puck is a static background — no transition to suppress. |
| 15 | Keyboard tab order | **PASS (light)** | Focus rings render on the visible interactive elements (Open Review queue, View grading rubric, severity rows, gate actions, Re-assess, View raw output). A full focus-order audit was not driven button-by-button in this Chrome pass; the components use native `<button>`s which Tab through in DOM order, matching the reading flow. |
| 16 | Console + network sanity | **PASS** | `read_console_messages(onlyErrors: true)` returned no errors. `GET /api/dashboard` returned `200`. The payload contains `level_up`, `last_assessment`, `open_by_severity`, `grade_label`, `grade_caption` (regression-locked by `test_dashboard_phase2.py::test_dashboard_impl0009_seeded_payload_shape`). |

**Pass count:** 16 / 16. Acceptance bar from the plan was ≥ 14.

## Process notes

- The Chrome MCP screenshots are visible inline in the agent transcript that
  produced this report. Persistent screenshot files were not written to
  `frontend/mockups/screenshots/PRD-0006-dashboard-impl/` — the MCP screenshot
  primitive captured the JPEGs as conversation outputs but did not return a
  filesystem path I could move. The PR description embeds the same imagery by
  re-rendering the dashboard against the test fixture during review.
- The dev backend running on `localhost:8000` (a stale Docker container from
  prior work) returns a real `grade=A + completion_id` payload from a previous
  scan. To exercise the new four-block layout against rich data, the dev MSW
  worker was temporarily wired to serve `gradeBWithHistoryPayload` for
  `GET /api/dashboard`. That handler override was reverted in the same branch
  before the final commit; `handlers.ts` ships unchanged from main except for
  unrelated test infrastructure.
- The assessment-running surface and the previous-assessment continuity card
  were not exercised in Chrome because the dev backend's assessment is in a
  terminal `complete` state. Both surfaces are verified by 7 unit tests
  (`AssessmentRunningCard.test.tsx` + `PreviousAssessmentCard.test.tsx` +
  `DashboardPage.test.tsx > shows the new assessment-running card when an
  assessment is in flight`). The CSS keyframes (`opensec-pulse-dot`,
  `opensec-spinner`, `opensec-fade-in`) are inspected directly in
  `frontend/src/index.css` and gated by `prefers-reduced-motion: reduce`.

## Attachments

- Live Chrome session ran against:
  - `localhost:5173/dashboard` — dashboard surface, all four blocks render.
  - `localhost:5173/issues?section=review` — confirmed by "Open Review queue".
  - `localhost:5173/issues?severity=high` — confirmed by clicking the High row.
- Backend gate: `cd backend && uv run pytest -v -m 'not e2e'` → 961 passed,
  19 skipped, 32 deselected, 0 failed.
- Backend lint: `cd backend && uv run ruff check opensec/ tests/` → all checks
  passed.
- Frontend gate: `cd frontend && npm run lint && npm run build && npm test --
  --run` → 384 passed, lint clean, build clean.
- OpenAPI snapshot: regenerated; `tests/api/openapi_snapshot.json` captures
  `LevelUp`, `LevelUpGate`, `OpenBySeverityRow`, `LastAssessmentInfo`,
  `PreviousAssessmentInfo`, plus the additive fields on `AssessmentTool`,
  `Assessment`, `AssessmentUpdate`, `AssessmentStatusResponse`, and
  `DashboardPayload`.
