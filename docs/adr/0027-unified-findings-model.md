# ADR-0027: Unified findings model

**Date:** 2026-04-19
**Status:** Proposed
**Context PRD:** PRD-0003 (Security assessment v2)
**Relates to:** ADR-0007 (domain model), ADR-0022 (LLM-powered finding normalizer), ADR-0023 (async chunked ingestion), ADR-0025 (assessment engine), ADR-0028 (subprocess-only scanner execution, supersedes ADR-0026)
**Amends:** ADR-0007 §Finding (adds `type`, `grade_impact`, `category`, `assessment_id` columns), ADR-0025 §posture storage (deprecates `posture_check` table)

---

## Context

PRD-0003 brings three new producers of "things the user should know about their repo" into the assessment pipeline:

1. **Trivy** — dependency vulnerabilities and leaked secrets
2. **Semgrep** — SAST code findings
3. **Expanded posture checks** — 15 repo-hygiene checks across 4 categories, with a new advisory/pass-fail distinction

Today these three producers persist in completely different ways:

| Producer | Where it lives today | Problem |
|----------|---------------------|---------|
| Dependency vulns (OSV/GHSA lookups) | In-memory `AssessmentResult.findings`, **never persisted** | No durable record, no remediation workflow possible, re-scan means re-lookup |
| Posture checks | Separate `posture_check` table, tied to `assessment_id` | Different status lifecycle, separate DAO, separate API, can't flow into the Findings page or the remediation workflow |
| External scanners (Snyk/Wiz/CSV upload) | `finding` table (via `POST /findings/ingest` + LLM normalizer) | Works, but is the only path — internal scanners bypass it |
| Semgrep (new in PRD-0003) | Not yet decided | — |

Meanwhile, the app architecture *already* treats a Finding as the unit of remediation: a Workspace opens on one Finding, an AgentRun enriches one Finding, the Findings page lists them. Every new producer that sits outside the `finding` table needs its own UI and its own workflow — which defeats the point of a single chat-led workspace.

### What we want

- **One storage model for everything the user might need to act on.** A vulnerable dependency, a leaked AWS key, a SQLi pattern Semgrep flagged, and a failing branch protection check are all "items in a backlog" from the user's perspective. They should share status lifecycle, ownership, workspace flow, and ticketing.
- **A typed taxonomy** so the UI can filter / group / tab on semantic type without grepping titles.
- **Idempotent re-scans.** Running the assessment twice on the same repo should update existing rows, not duplicate them.
- **Extensibility.** Tomorrow we add container scanning, IaC scanning, or CSPM — adding a new type should be a one-line enum change, not a new table.
- **The Findings page roadmap.** CEO plans to extend the Findings page to show all types in upcoming work. Backend must be ready now so the UI feature is a pure frontend change.

---

## Decision

### 1. One `finding` table. Four types.

Add a `type` column to the `finding` table with this enum:

| `type` | Meaning | Typical `source_type` |
|--------|---------|-----------------------|
| `dependency` | Vulnerable third-party dependency | `trivy`, `snyk`, `wiz`, `dependabot` |
| `code` | Static-analysis finding in the repo's own code | `semgrep`, `codeql` |
| `secret` | Leaked credential / key detected in source | `trivy-secret`, `gitleaks` |
| `posture` | Failing or advisory repo-hygiene check | `cliff-posture` |

**Naming rationale:** CEO called out that "vulnerability" is ambiguous because posture issues and code issues are *also* vulnerabilities in the colloquial sense. `dependency` is precise: it describes the *what* (a dependency), and severity/exploitability live on other columns. `code` covers SAST and `secret` gets its own type because leaked credentials have a distinct remediation path (rotate + scrub) that differs from both dependency upgrades and code fixes.

Both `source_type` (which tool reported it) and `type` (semantic category) are kept. Trivy reports both `dependency` and `secret` findings — same tool, two types.

### 2. Two additional columns to absorb posture semantics

| Column | Values | Purpose |
|--------|--------|---------|
| `grade_impact` | `counts` \| `advisory` | Does this finding affect the repo's grade? `counts` means yes (most findings). `advisory` means no — informational only (posture `workflow_trigger_scope`, `broad_team_permissions`, `signed_commits`). Advisory findings can be filtered out of the default queue. Default `counts`. |
| `category` | free-text (nullable) | Grouping label for posture findings only in v1: `ci_supply_chain`, `collaborator_hygiene`, `code_integrity`, `repo_configuration`. For `dependency`, `code`, `secret` types: leave null. If OWASP/CWE grouping is wanted for SAST later, add a dedicated enum — do not re-purpose this column. |

### 3. Nullable `assessment_id` FK

Add `assessment_id TEXT REFERENCES assessment(id) ON DELETE CASCADE` to link findings back to the scan that produced them. Null for externally-ingested findings (Snyk CSV uploads etc. have no assessment). This replaces the posture_check → assessment link and gives us per-assessment filtering for the dashboard.

### 4. Deprecate the `posture_check` table

- **What happens to it:** Migration drops it after moving any failing/advisory rows into `finding`.
- **What does *not* move:** Passing checks. Passing posture is captured by the `criteria_snapshot` JSON on `assessment` (source of truth for the grade). We do not pollute the findings backlog with "here's a thing that's fine".
- **What moves:** Every `fail` and `advisory` posture_check becomes one `finding` row with `type=posture`, `grade_impact=counts|advisory`, `category=<posture category>`, `status='new'` (or `'closed'` if an older assessment shows it subsequently passed — edge case, can be deferred).

### 5. Two normalization paths, one output

Every source now converges on `FindingCreate`:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            SOURCES OF FINDINGS                                │
└──────────────────────────────────────────────────────────────────────────────┘

  Trivy          Semgrep         GitHub API +           External payloads
  (vuln+secret)  (SAST)          repo file checks       (Snyk / Wiz / CSV)
       │              │                  │                      │
       ▼              ▼                  ▼                      ▼
  TrivyResult    SemgrepResult     PostureCheckResult       raw JSON dicts
  (Pydantic)     (Pydantic)        (Pydantic)               (untyped)
       │              │                  │                      │
       │              │                  │                      │
       ▼              ▼                  ▼                      ▼
┌──────────────────────────────────────────┐       ┌────────────────────────┐
│   DETERMINISTIC NORMALIZERS              │       │   LLM NORMALIZER       │
│   backend/cliff/assessment/            │       │   backend/cliff/     │
│     to_findings.py                       │       │     integrations/      │
│                                          │       │     normalizer.py      │
│   from_trivy_vulns(result)   → dependency│       │                        │
│   from_trivy_secrets(result) → secret    │       │   normalize_findings() │
│   from_semgrep(result)       → code      │       │   (LLM extracts type + │
│   from_posture(results)      → posture   │       │    FindingCreate fields│
│                                          │       │    from arbitrary JSON)│
└───────────────────┬──────────────────────┘       └────────────┬───────────┘
                    │                                           │
                    └──────────────────┬────────────────────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │     FindingCreate    │
                            │  (type, grade_impact,│
                            │   category,          │
                            │   source_type,       │
                            │   source_id, ...)    │
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │   create_finding()   │
                            │    UPSERT on         │
                            │  (source_type,       │
                            │   source_id)         │
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │    finding table     │
                            │    + type column     │
                            │    + grade_impact    │
                            │    + category        │
                            │    + assessment_id   │
                            └──────────┬───────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
    ┌─────────────┐            ┌───────────────┐          ┌─────────────────┐
    │ Findings    │            │  Dashboard    │          │  Workspace      │
    │ page        │            │  (type=       │          │  (remediation,  │
    │ (type=      │            │   posture,    │          │   works for any │
    │  filters)   │            │   grouped by  │          │   finding type) │
    └─────────────┘            │   category)   │          └─────────────────┘
                               └───────────────┘
```

Two paths exist because the cost profile is different:

- **Deterministic** (Trivy, Semgrep, posture) — we own the input schema. No LLM needed. Sub-millisecond per finding.
- **LLM** (external scanner payloads) — input schema is unknown/vendor-specific. LLM extraction is required. This is the existing `POST /findings/ingest` path.

Both emit `FindingCreate` and go through the same `create_finding()` persistence. No duplicate persistence paths.

### 6. Idempotent re-scans via UPSERT on `(source_type, source_id)`

Re-running an assessment on the same repo must not duplicate findings. The existing `idx_finding_source` index already enforces uniqueness-ish; we make it a formal UNIQUE constraint and switch `create_finding` to `INSERT ... ON CONFLICT DO UPDATE`.

**`source_id` conventions** (deterministic, reproducible across scans):

| Type | `source_id` format | Example |
|------|---------------------|---------|
| `dependency` | `{PkgName}@{InstalledVersion}:{VulnID}` | `lodash@4.17.19:CVE-2021-23337` |
| `secret` | `{path}:{startLine}:{RuleID}` | `src/config.js:42:aws-access-key-id` |
| `code` | `{path}:{startLine}:{check_id}` | `app/db.py:88:python.django.security.audit.sqli` |
| `posture` | `{repo_url}:{check_name}` | `github.com/gal/repo:actions_pinned_to_sha` |
| External (LLM) | whatever the scanner provides | `snyk:SNYK-JS-LODASH-567746` |

Re-running an assessment refreshes `updated_at`, `raw_payload`, `detail`, and `description` on existing rows; it does not reset user-set fields like `status` (unless the underlying issue is gone — see §7).

### 7. Lifecycle: what happens when a finding disappears from a scan

When a re-scan no longer reports a finding that previously existed (dependency upgraded, secret scrubbed, posture check now passes), the finding is marked `status='closed'` with a system note. This is how the badge stays honest and the workspace flow knows "this is fixed." The user can still see closed findings in history.

**Scoping rule — close only what you own.** The stale-close pass must be scoped by the `source_type` that just ran, not by `type`. Example: if today's Trivy scan produces a different set of findings than last week's, we close the Trivy-origin findings that disappeared; we do **not** touch findings whose `source_type` is `snyk` or `wiz` from an earlier external import, even though they share `type='dependency'`. Each producer closes only its own output.

**Scanner must have run.** A `source_type` whose scanner was `skipped` or failed this assessment does not trigger a close pass. An `unknown`-status posture check (e.g., GitHub API rate-limited) does not close the corresponding finding — absence of signal is not evidence of fix.

### 8. API impact — backwards-compatible default

`GET /findings` gets a `type` query parameter. To preserve current behavior (the Findings page today shows only dependency-ish things), the **default when no type is specified is `type=dependency`**. Explicit filters:

- `GET /findings?type=dependency` — today's behavior (default)
- `GET /findings?type=code,secret` — code issues + secrets
- `GET /findings?type=all` or `GET /findings?type=dependency,code,secret,posture` — everything
- `GET /findings?grade_impact=counts` — exclude advisory findings
- `GET /findings?assessment_id=...` — scoped to one scan

The dashboard's grouped posture section moves from its own DAO to `GET /findings?type=posture&assessment_id=latest` (both `counts` and `advisory` grade_impact are returned, since the UI renders them together), grouped client-side by `category`. Dashboard still reads the grade from `assessment.criteria_snapshot` — that does not change.

### 9. What we are **not** changing

- The `raw_payload` JSON column keeps the original vendor/tool payload for evidence. Unchanged.
- The `status` enum stays `new | triaged | in_progress | remediated | validated | closed | exception`. Posture findings use the same lifecycle — "fail → generator agent fix → validated" maps cleanly.
- The `AssessmentResult` Pydantic object (in-memory) still exists; it just now persists every field into `finding` rows instead of keeping them in memory.
- External `POST /findings/ingest` LLM flow is unchanged except the prompt adds a `type` field (defaulting to `dependency` when ambiguous) — one prompt tweak, no architecture change.
- The Findings page frontend is untouched for now. Filter UI and multi-type display lands in a follow-up feature. Backend readiness is the point.

---

## Schema changes

### Migration `009_unified_findings.sql`

The migration runs in two phases: a **pre-check** (fail-fast with a clear error if the DB isn't safe to migrate), and the **migration proper** (wrapped in a transaction).

```sql
-- Phase 0: pre-check (run in application code before executing the .sql file).
-- Query:
--   SELECT source_type, source_id, COUNT(*) AS n
--   FROM finding
--   GROUP BY source_type, source_id
--   HAVING n > 1;
-- If this returns any rows, abort migration with an error listing them and
-- instructing the operator to resolve manually. Do NOT auto-delete duplicates.
-- This is destructive data that only the operator can judge.

-- Phase 1: schema + data changes (transactional).
BEGIN;

-- 1. Extend finding table
ALTER TABLE finding ADD COLUMN type TEXT NOT NULL DEFAULT 'dependency';
ALTER TABLE finding ADD COLUMN grade_impact TEXT NOT NULL DEFAULT 'counts';
ALTER TABLE finding ADD COLUMN category TEXT;
ALTER TABLE finding ADD COLUMN assessment_id TEXT REFERENCES assessment(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_finding_type ON finding(type);
CREATE INDEX IF NOT EXISTS idx_finding_assessment ON finding(assessment_id);
-- Enforce idempotent re-scans. Will fail loudly if pre-check missed duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_finding_source ON finding(source_type, source_id);

-- 2. Migrate failing/advisory posture_check rows into finding
INSERT INTO finding (
    id, source_type, source_id, type, grade_impact, category,
    title, description, status, raw_payload,
    assessment_id, created_at, updated_at
)
SELECT
    pc.id,
    'cliff-posture',
    (SELECT repo_url FROM assessment WHERE id = pc.assessment_id) || ':' || pc.check_name,
    'posture',
    CASE pc.status WHEN 'advisory' THEN 'advisory' ELSE 'counts' END,
    NULL,  -- category backfilled by app on next assessment
    pc.check_name,
    pc.detail,
    'new',
    pc.detail,
    pc.assessment_id,
    pc.created_at,
    pc.created_at
FROM posture_check pc
WHERE pc.status IN ('fail', 'advisory');

-- 3. Drop the old table
DROP INDEX IF EXISTS idx_posture_check_assessment;
DROP TABLE IF EXISTS posture_check;

COMMIT;
```

### Model changes

```python
# backend/cliff/models/finding.py
FindingType = Literal["dependency", "code", "secret", "posture"]
FindingGradeImpact = Literal["counts", "advisory"]

class FindingCreate(BaseModel):
    source_type: str
    source_id: str
    type: FindingType = "dependency"          # NEW
    grade_impact: FindingGradeImpact = "counts"  # NEW
    category: str | None = None               # NEW
    assessment_id: str | None = None          # NEW
    title: str
    # ...rest unchanged
```

`models/posture_check.py` is deleted. `PostureCheckResult` (the in-pipeline Pydantic type from Epic 2 of IMPL-0003) stays — it's the shape the posture module emits to the normalizer, not a DB row.

---

## Consequences

**Easier:**

- Findings page can show every security backlog item in one list with one filter UI. No per-type routing.
- Workspace / remediation flow works the same for posture fixes, dependency upgrades, and SAST fixes — one code path.
- Adding a new type (container scan, IaC scan, CSPM) is: add an enum value + write a `from_xxx()` normalizer. No new table, no new DAO, no new API route.
- Idempotent re-scan for free — the UPSERT means assessment runs become safe to retry.
- Deletes the `posture_check` table and its DAO (~200 lines of code gone).

**Harder:**

- Migration is destructive for `posture_check`. Only failing/advisory rows carry forward. Acceptable — posture history is a "nice to have", not a product requirement.
- Unique `(source_type, source_id)` means we must pick `source_id` schemes that are deterministic across scans. Getting this wrong means either duplicates (too loose) or masking distinct findings (too tight). The conventions in §6 are explicit to keep this honest.
- `GET /findings` default behavior changes from "all rows" to "type=dependency". Justified because today all rows *are* dependencies; in two weeks they will not be, and silent drift is worse than an explicit default.

**Risks:**

| Risk | Mitigation |
|------|------------|
| `source_id` collisions between tools (e.g., two scanners both use `CVE-2021-23337`) | `source_type` is part of the unique key. Two tools finding the same CVE produce two findings — acceptable, maybe even desirable for cross-referencing. |
| Advisory findings flood the queue | `grade_impact=advisory` is excludable by default in queries. Dashboard shows advisory count separately. |
| Posture "disappearance" mis-detection closes findings incorrectly | A posture check that becomes `unknown` (API failure) must NOT close the finding. Only a transition to `pass` closes it. |
| Migration loses historical posture data | Acceptable — passing checks are recoverable from `criteria_snapshot`; failing ones migrate. |

---

## Alternatives considered

**A. Keep three tables (`finding`, `posture_check`, plus new `code_finding`).** Rejected: triples the UI surface, triples the DAOs, and every new producer adds another table. This is the status quo we're moving away from.

**B. One table but no `type` column; infer type from `source_type` string.** Rejected: forces every filter, every UI branch, and every grouping to grep substrings. A column is 8 bytes; brittle string matching is forever.

**C. Store posture passes as findings too (with status `closed` or `passed`).** Rejected: pollutes the backlog. The grade snapshot is the right home for "state of the world across criteria." Findings are for "things to act on."

**D. Put the LLM normalizer in front of Trivy/Semgrep too for uniformity.** Rejected by the same logic as ADR-0026/ADR-0028: we own the schema, so paying LLM cost to parse it is waste. Two deterministic functions beat a speculative abstraction.

---

## Follow-ups

- Findings page frontend feature: add type tabs, advisory toggle, and `type=all` default. Tracked separately after IMPL-0003 merges.
- `finding-normalizer` agent prompt: add `type` field extraction. Small prompt tweak, landed as part of IMPL-0003 Epic 3b (see IMPL-0003 amendment).
- When an external adapter (Snyk, Wiz) is added to the integration-framework roadmap, its mock and real wrappers emit `FindingCreate` with appropriate `type`. No schema work needed at that point.
