# ADR-0032: Dashboard payload shape for security assessment v2

**Date:** 2026-04-25
**Status:** Proposed
**PRD:** PRD-0003 v0.2 — Security assessment v2 (rev. 2)
**Plan:** IMPL-0003 rev. 2, Epic 4 (and the schema fields that bleed into Epics 3 + 5 + 6)
**Relates to:** ADR-0011 (Stitch design system), ADR-0027 (unified findings model), ADR-0029 (warning design token)

## Context

PRD-0003 (rev. 1) was approved against an early sketch of the assessment dashboard payload that grew organically inside IMPL-0003: a `scanner_versions` map for tool identity, a parallel `tool_states[]` array for per-tool state, a flat 10-bool `criteria_snapshot` JSON, posture-check rows shaped as `{passed: bool}`, and a client-side query-param trick (`?assessment=complete`) to gate the assessment-complete interstitial.

A design pass produced six new surfaces (the report-card hero, assessment progress with scanner stages, an assessment-complete interstitial, onboarding step 3, completion progress card, and the share card — staged at `frontend/mockups/claude-design/`). Reading the design carefully revealed that the original payload shape collapses or omits four things the new surfaces depend on:

1. **Per-tool result counts.** The report-card hero `Scanned by` row reads "Trivy 0.52 · 7 findings · Semgrep 1.70 · 3 findings · 15 posture checks · 12 pass". `scanner_versions` is just versions — no counts. Counts could be derived client-side from `vulnerabilities.by_source`, but they belong with tool identity, not in a parallel structure that has to be stitched together at render time.
2. **A "done" posture-check state.** When an Cliff agent's PR has merged a fix, the row shows a `Draft PR ↗` link to GitHub. `passed: bool` collapses "was always fine" with "we fixed this for you" — the brand moment of Cliff earning the user's trust gets erased at the schema level.
3. **Labels for the criteria.** The completion-progress card's subtitle reads "*2 criteria remaining: pin CI actions to SHA, add code owners.*" The criteria need labels next to their booleans. A static frontend label map works but bifurcates copy ownership; if product changes a criterion name, two PRs ship instead of one.
4. **A reload-safe gate for the interstitial.** Surface 3 must show after the first assessment after onboarding, then never again unless the posture-check count changes. A URL query param doesn't survive a refresh; localStorage doesn't survive a fresh container; an in-memory React flag doesn't survive a navigation away. The single-user community edition has a database — it should hold this state.

We considered four ways to address the cluster:

| Option | Sketch | Verdict |
|---|---|---|
| A · Patch the existing payload in place | Add `tool_results: {trivy: 7, ...}` next to `scanner_versions`; add `state` next to `passed`; add `criteria_labels: {key: label}` map; keep the URL-param interstitial | Rejected. Doubles the wire shape without removing the old fields, and leaves drift opportunities (e.g., what happens when `passed=false` but `state='done'`?). The redundant field problem PRD-0004 just retired in the workspace nav reappears here |
| B · One ADR per concern (four small ADRs) | One ADR for tool payload, one for posture state, one for criteria labels, one for interstitial gate | Rejected. The decisions are co-located on a single endpoint and a single migration. Splitting them adds review overhead without clarifying anything |
| C · This ADR — coherent rev. 2 payload shape | Replace `scanner_versions` + `tool_states[]` with `tools[]`; replace `passed: bool` with `state: pass\|fail\|done\|advisory` (read-time projection); return `criteria` as a labeled list; add `summary_seen_at` column + `mark-summary-seen` endpoint | **Chosen** |
| D · Defer until v0.3, ship v0.2 with the old shape | Frontend uses the design but compromises on the four surfaces above | Rejected. The "Trivy 0.52 · 7 findings" rendering is the brand-trust moment of the dashboard. Compromising it means shipping the design at lower fidelity than the product deserves |

Option C earns its complexity by collapsing two parallel structures (`scanner_versions` + `tool_states[]`) into one, by introducing `done` as a first-class posture state that maps directly to "we fixed this for you, here's the PR", and by making the interstitial gate a single-row column-and-endpoint pair instead of a localStorage-and-URL dance.

## Decision

The four schema-shape decisions ride together as a coherent commitment for IMPL-0003 rev. 2.

### 1. `tools[]` replaces `scanner_versions` + `tool_states[]`

A single `tools[]` payload — present on every endpoint that touches an assessment (`/dashboard`, `/assessment/latest`, `/assessment/status/{id}`) — carries identity, state, and result counts together.

```python
@dataclass
class AssessmentToolResult:
    kind: Literal["findings_count", "pass_count"]
    value: int
    text: str  # display-ready ("7 findings", "12 pass") — backend owns the copy

@dataclass
class AssessmentTool:
    id: str                              # "trivy" | "semgrep" | "posture"
    label: str                           # "Trivy 0.52" — user-facing identity
    version: str | None                  # "0.52.0"; null for the synthetic posture tool
    icon: str                            # Material Symbol name ("bug_report" | "code" | "rule")
    state: Literal["pending", "active", "done", "skipped"]
    result: AssessmentToolResult | None  # populated on done; null otherwise
```

Persisted as `tools_json TEXT` on the `assessment` table (migration `008a_assessment_tools.sql`, replacing the originally-planned `008a_scanner_versions.sql`).

Counts derive from filtered queries against the unified `finding` table (per ADR-0027):

| Tool | Count source |
|---|---|
| Trivy | `count(finding) WHERE source_type IN ('trivy', 'trivy-secret') AND assessment_id = X` |
| Semgrep | `count(finding) WHERE source_type = 'semgrep' AND assessment_id = X` |
| Posture | `count(finding) WHERE type = 'posture' AND state = 'pass' AND assessment_id = X` (text reads "X pass") |

The legacy `scanner_versions` field is removed entirely. PRD-0003 has not shipped, so there are no existing API consumers to break.

### 2. Posture-check `state` replaces `passed: bool`

Each posture check on the wire carries `state: "pass" | "fail" | "done" | "advisory"`:

| State | When | Visual treatment (per design) |
|-------|------|-------------------------------|
| `pass` | Check ran, passed, no agent involvement | Filled `check_circle` in `text-tertiary` |
| `fail` | Check ran, failed; may be `fixable_by` an agent | Filled `cancel` in `text-error`, card-style row in `bg-primary-container/30` |
| `done` | Check failed previously; an Cliff agent's PR fixed it. `pr_url` is non-null | Filled `check_circle` + right-aligned `Draft PR ↗` link |
| `advisory` | Informational, doesn't count toward the grade | Outline `info`, right-aligned `advisory` chip |

`done` is a **read-time projection**, not a property of the in-pipeline `PostureCheckResult` DTO. The pipeline only ever produces `pass | fail | advisory`. The `/dashboard` route projects to `done` when it sees a posture finding (`type='posture'` in the unified `finding` table) with `status` in (`remediated`, `closed`) AND `raw_payload.pull_request.url` set. The `pr_url` field on the wire passes through `raw_payload.pull_request.url` directly. No new persisted column.

This deliberately aligns the dashboard's posture vocabulary with PRD-0004 Story 3's four-state row pattern (To do / Running / Done / Failed) — same number of states, same semantic shape — so the same `PostureCheckItem` component can render both an in-flight remediation row and a completed-via-agent row.

### 3. Labeled `criteria[]` replaces the bare boolean snapshot

The on-disk `CriteriaSnapshot` (10 booleans, JSON-encoded on the assessment row) stays unchanged. The API layer wraps it at response time:

```jsonc
"criteria": [
  { "key": "security_md_present",       "label": "SECURITY.md present",         "met": true },
  { "key": "no_high_vulns",             "label": "No high vulns",               "met": false },
  ... // 10 entries total, fixed order
]
```

The label map lives in `backend/cliff/api/routes/dashboard.py` (or a sibling module). Backend owns the copy; product can change a criterion label in one PR; the frontend renders whatever the backend returns. The fixed order is the order in which criteria appear on Surface 5's chip grid.

### 4. `summary_seen_at` server flag + `mark-summary-seen` endpoint replaces the URL trick

Add `summary_seen_at TEXT NULL` to the `assessment` table (migration `008b_assessment_summary_seen.sql` — one-line `ALTER`). Existing rows default to `NULL`, which means they re-show the interstitial once after upgrade — acceptable for the single-user community edition.

A new minimal endpoint:

```http
POST /api/assessment/{id}/mark-summary-seen
```

Empty request body. Idempotent: first call sets `summary_seen_at` to `now()`; subsequent calls return the same timestamp without rewriting. Response includes the timestamp:

```jsonc
{ "assessment": { "id": "asm_...", "summary_seen_at": "2026-04-25T11:10:00Z" } }
```

Frontend gate (in `DashboardPage.tsx`):

```ts
const showInterstitial =
  dashboardData?.assessment?.status === 'complete' &&
  dashboardData?.assessment?.summary_seen_at == null;
```

The "View your report card" CTA fires `markSeen.mutate(assessmentId)`; the dashboard query invalidates; the next render falls through to the report card. No URL plumbing, no localStorage.

This is a tiny pattern but it does establish a precedent. If a sibling one-shot acknowledgment lands later (e.g., "user has dismissed the badge-installation walkthrough"), the same shape — nullable timestamp column + idempotent POST endpoint — is the path.

## Consequences

**Easier:**

- The Trivy-version-and-count rendering on the report-card hero is one component reading one field, not three components stitching `scanner_versions`, `tool_states`, and `vulnerabilities.by_source` together.
- "Pass" and "agent fixed this" are visually and semantically distinct on the dashboard. The brand moment of Cliff earning trust isn't collapsed at the schema level.
- Criteria copy lives in one place. Product changes a label in one PR.
- The interstitial gate survives reloads, container restarts, and tab navigations. Single-user community edition uses the database it already has.
- Same `PostureCheckItem` component works for in-flight remediation rows (PRD-0004 Story 3) and read-time done rows (this ADR). The four-state vocabulary is consistent across both surfaces.

**Harder:**

- `tools[]` replacing `scanner_versions` is a wire-shape change. Nothing has shipped against the rev. 1 shape, so there's nothing to break — but the legacy field reappearing in any future read path would be a regression. Epic 4 has an explicit `test_dashboard_omits_legacy_scanner_versions` test as the regression guard.
- The posture `state` projection is a read-path computation that joins finding state with posture metadata. Slightly more work in the dashboard route than reading a flat `passed` bool. Bounded: still one query per assessment, indices already in place.
- `summary_seen_at` adds a column. One-line migration; defaults are correct; cost is the migration itself.
- Labeled criteria adds a label map to maintain. Ten entries; copy is stable; cost is one constant in one file.

**Known gaps:**

- The `tools[]` payload bakes a small amount of presentation into the backend (`label: "Trivy 0.52"`, `icon: "bug_report"`). This is a deliberate trade — the backend already knows the version, and the frontend rendering is one-to-one with the backend's identity model. If we ever ship localized UIs or theme-pluggable tool icons, those move to the frontend; today they don't earn the abstraction.
- The four-state posture vocabulary leaves no room for transient "running" or "queued" states on read. That's correct for the dashboard (which reads completed assessments), and PRD-0004 Story 3's optimistic flip handles the in-flight states client-side. If we ever need a server-rendered "queued" or "running" remediation row, it's a fifth state to add then — not a redesign.

## Revisit

If `mark-summary-seen` proliferates to other one-shot acknowledgments (badge walkthrough, generator-PR-merged toast, etc.) we promote the pattern to a generic `acknowledgments` table and retire the per-assessment column. Until then, three similar lines beat a premature abstraction.

If localization lands, the `label`-on-the-server choice for tools and criteria gets revisited. Likely move: server returns `label_key`, frontend resolves through an i18n table.
