# IMPL-0003: Security assessment v2

**PRD:** docs/product/prds/PRD-0003-security-assessment-v2.md (rev. 2, 2026-04-25)
**UX Spec:** docs/design/specs/UX-0003-security-assessment-v2.md (rev. 1) — superseded for Surfaces 1–6 by the Claude design hand-off at `frontend/mockups/claude-design/` (canonical visual reference)
**Design hand-off:** frontend/mockups/claude-design/ (`README.md`, `surfaces/*.jsx`, `colors_and_type.css`)
**Design delta source:** frontend/mockups/claude-design/IMPL-DELTA.md
**ADRs:** ADR-0027 (unified findings), ADR-0028 (subprocess-only scanner execution, supersedes ADR-0026), ADR-0029 (warning design token)
**Status:** Draft · rev. 2 (2026-04-25)
**Date:** 2026-04-18 · rev. 2 amended 2026-04-25
**Delivery:** Single PR, single Claude Code session

### Revisions

- **rev. 1 (2026-04-19)** — Epic 3b added for the unified findings model (ADR-0027); Epic 1 collapsed to subprocess-only (ADR-0028).
- **rev. 2 (2026-04-25)** — Refreshed against the Claude-design hand-off staged at `frontend/mockups/claude-design/`. Schema-shape changes: a single `tools[]` payload replaces the parallel `scanner_versions` + `tool_states[]` pair (per-tool result counts now flow through one shape); each posture check moves from `passed: bool` to a `state: "pass" | "fail" | "done" | "advisory"` field aligned with PRD-0004 Story 3; `criteria` is returned as a labeled list, not a bare snapshot; `summary_seen_at` lands on the assessment row; medium-severity chips use the new `warning` token (ADR-0029). New Epic 0 stands up the Serene Sentinel global CSS utilities (`spinner`, `animate-pulse-subtle`, `grade-ring`, `msym-filled`) before any frontend epic compiles.

---

## Summary

Replace Cliff's homebrew lockfile parsers and OSV.dev lookups with Trivy and Semgrep, expand posture checks from 7 to 15, recalibrate the grade from 5 to 10 criteria, and update the frontend to show scanner-specific progress, grouped posture categories, and an assessment-complete summary interstitial.

### Key architectural decisions

| Decision | Choice | ADR / Source |
|----------|--------|--------------|
| Scanner execution | Subprocess-only (no Docker runner) | ADR-0028 |
| Binary trust | Pinned SHA256 checksums of GitHub-release binaries in `.scanner-versions`; verification is strict by default | ADR-0028 |
| Scanner env | Minimal env whitelist for scanner subprocess; GitHub PAT explicitly excluded | ADR-0028 |
| Old parsers | Delete entirely (Trivy replaces them) | ADR-0026 §"Homebrew parsers removed" (still in force) |
| Repo cloning | Simple `git clone` subprocess function (no RepoCloner abstraction) | — |
| Assessment summary | Per-assessment `summary_seen_at` column on the `assessment` row + a one-shot `mark-summary-seen` endpoint. Survives reload, single-user friendly, beats local-storage | rev. 2 (this plan) |
| Finding storage | Unified `finding` table; 4 types (dependency/code/secret/posture); `posture_check` table deprecated | ADR-0027 |
| Tool identity payload | Single `tools[]` array replaces the parallel `scanner_versions` + `tool_states[]` pair. Each entry: `{id, label, version, icon, state, result?}`. Same shape on `/dashboard` and `/assessment/status/{id}` | rev. 2 (design delta) |
| Posture-check state vocabulary | `state: "pass" \| "fail" \| "done" \| "advisory"` replaces `passed: bool`. `done` distinguishes "an Cliff agent fixed this and here's the PR" from `pass` (was always fine) — design relies on this | rev. 2 (design delta), aligned with PRD-0004 Story 3 |
| Criteria response shape | Labeled list `criteria: [{key, label, met}]`. Backend owns the labels; the on-disk JSON snapshot is wrapped at response time | rev. 2 (design delta) |
| Medium severity color | Uses `warning-container/40` + `on-warning-container` (NOT `tertiary-container`). The Claude design's `SeverityChip` defaulted medium to tertiary — that mapping is overridden by ADR-0029 in our codebase | ADR-0029 |
| Hero narrative copy | Frontend-derived from `criteria_met / total` + count of fixable failing posture checks. Backend returns numbers, frontend picks the headline | rev. 2 |

---

## Epic structure

This PR is organized as 8 sequential epics. Each epic is independently testable — tests must pass after each epic before moving to the next.

```
Epic 0:  Design tokens / CSS utilities   (frontend — small, blocks Epics 5/6)
Epic 1:  Scanner infrastructure          (backend — new code)
Epic 2:  Posture expansion               (backend — extend existing)
Epic 3:  Assessment engine rewrite       (backend — rewrite existing)
Epic 3b: Unified findings model          (backend — schema + normalizer + persistence) [ADR-0027]
Epic 4:  API + schema updates            (backend — modify existing)
Epic 5:  Frontend new components         (frontend — new files)
Epic 6:  Frontend page updates           (frontend — modify existing)
```

> Epic 0 is a 30-minute stand-up of global CSS utilities and tailwind config additions. It must land before Epic 5 because the new components reference its keyframes and helper classes. It can run in parallel with Epics 1–3b on a separate branch if needed.
>
> Epic 3b sits after Epic 3 so that the engine rewrite can be written *directly against* the new `FindingCreate(type=...)` contract. Epic 3 produces the typed scanner results; Epic 3b persists them. Epics 1, 2, 3, 3b are backend-only and can ship before the frontend epics land.

---

## Epic 0: Design tokens and global CSS utilities

**Goal:** Land the small set of global CSS utilities the Claude-design surfaces depend on, before any frontend component referencing them is written.

### Files to create

| File | Purpose |
|------|---------|
| `frontend/src/styles/serene-sentinel.css` | Hosts the design utilities below. Imported once from `frontend/src/main.tsx` |

### Files to modify

| File | Changes |
|------|---------|
| `frontend/tailwind.config.ts` | Add `fontFamily.mono: ['JetBrains Mono', 'monospace']`. Confirm `fontFamily.headline = ['Manrope', ...]` and `body = ['Inter', ...]` already match (yes, per current config). No new color tokens — `warning` family already landed via ADR-0029 |
| `frontend/src/main.tsx` | Import `./styles/serene-sentinel.css` once (after `index.css`) |
| `frontend/index.html` | Verify the Material Symbols and JetBrains Mono fonts are loaded. The Manrope + Inter import is already in place |

### Utilities to ship in `serene-sentinel.css`

```css
/* Filled-variant Material Symbol (e.g., check_circle in tertiary) */
.msym-filled { font-variation-settings: 'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 24; }

/* Spinner used in running rows + active tool pills */
.spinner   { width: 14px; height: 14px; border-radius: 9999px;
             border: 2px solid rgba(77,68,227,0.3); border-top-color: #4d44e3;
             animation: spin 0.9s linear infinite; display: inline-block; }
.spinner-lg { width: 28px; height: 28px; border-width: 3px; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Subtle pulse for the active tool pill (2.4s) */
@keyframes pulse-subtle { 0%, 100% { opacity: 1; } 50% { opacity: 0.65; } }
.animate-pulse-subtle { animation: pulse-subtle 2.4s ease-in-out infinite; }

/* Conic-gradient grade ring; consumer sets --p as a percentage */
.grade-ring { background: conic-gradient(var(--primary, #4d44e3) var(--p, 0%),
                                          var(--primary-fixed-dim, #d2d0ff) 0); }

/* Share-card paper texture (Surface 6) */
.share-card { background:
  radial-gradient(ellipse at top right, rgba(255,255,255,0.06), transparent 50%),
  radial-gradient(ellipse at bottom left, rgba(255,255,255,0.04), transparent 60%),
  linear-gradient(135deg, #2a13c5 0%, #4034d7 50%, #4d44e3 100%);
}

/* Reduced motion respect */
@media (prefers-reduced-motion: reduce) {
  .spinner, .spinner-lg, .animate-pulse-subtle { animation: none; }
}
```

### Tests (write first)

1. `test_serene_sentinel_css_imports` — verify `main.tsx` imports the file (string presence test in the bundled output)
2. Visual smoke (Vitest + Testing Library): render a `<div className="spinner" />` — assert it's in the document and has `animation` set to a non-empty value via computed styles. Same for `.animate-pulse-subtle`.
3. Visual smoke for `.grade-ring`: render `<div className="grade-ring" style={{ '--p': '60%' }} />` and assert its `background-image` contains `conic-gradient`.

### Out of scope

- The `warning` token family — already landed via ADR-0029 / IMPL-0004 T5. Don't re-introduce.
- The four-state posture-row pattern itself — landed via PRD-0004 Story 3. This epic only adds the CSS atoms used by the new design.

---

## Epic 1: Scanner infrastructure

**Goal:** Trivy and Semgrep can be invoked as verified-pinned subprocess binaries and their JSON output parsed into typed Python models. Per [ADR-0028](../../adr/0028-subprocess-only-scanner-execution.md), there is exactly one runner.

### Files to create

| File | Purpose |
|------|---------|
| `.scanner-versions` | Pinned version, GitHub release URL, and SHA256 checksum for each scanner binary (NOT Docker image digests — see ADR-0028 §"Supply chain defense") |
| `scripts/install-scanners.sh` | Downloads Trivy + Semgrep from their GitHub release URLs in `.scanner-versions`, verifies SHA256 against the pinned values, installs to `bin/` — mirrors `scripts/install-opencode.sh`. Called by `scripts/dev.sh` and by `docker/Dockerfile` at image build time. Aborts on checksum mismatch (strict mode) |
| `backend/cliff/assessment/scanners/__init__.py` | `ScannerRunner` protocol + single `create_scanner_runner()` factory returning the subprocess runner |
| `backend/cliff/assessment/scanners/runner.py` | Subprocess runner — the sole `ScannerRunner` implementation. Spawns Trivy/Semgrep with a minimal env whitelist (`PATH`, `HOME`, `LANG`, `TRIVY_CACHE_DIR`, `SEMGREP_RULES_CACHE_DIR`). **Does NOT propagate `GITHUB_PAT` or other Cliff secrets.** Enforces timeout + non-root |
| `backend/cliff/assessment/scanners/models.py` | `TrivyResult`, `SemgrepResult`, `ScannerInfo` Pydantic models |
| `backend/cliff/assessment/scanners/verify.py` | Runtime checksum verification helper — reads `.scanner-versions`, computes SHA256 of the resolved binary, compares. Honors `CLIFF_SCANNER_CHECKSUM_VERIFY=strict\|warn` (default `strict`) |
| `backend/cliff/assessment/clone.py` | `clone_repo(url, pat, dest) -> Path` — simple git clone subprocess |
| `tests/test_scanner_models.py` | Parse real Trivy/Semgrep JSON fixtures |
| `tests/test_scanner_runner.py` | Subprocess runner with mocked `asyncio.create_subprocess_exec` — asserts env whitelist, timeout enforcement, JSON parsing path |
| `tests/test_scanner_verify.py` | Checksum verification — matching checksum passes, mismatch aborts in strict mode and warns in warn mode |
| `tests/test_clone.py` | Clone function with mocked subprocess |
| `tests/fixtures/trivy_output.json` | Real Trivy JSON output fixture |
| `tests/fixtures/semgrep_output.json` | Real Semgrep JSON output fixture |

### Files to delete

| File | Reason |
|------|--------|
| `backend/cliff/assessment/parsers/npm.py` | Replaced by Trivy |
| `backend/cliff/assessment/parsers/pip.py` | Replaced by Trivy |
| `backend/cliff/assessment/parsers/golang.py` | Replaced by Trivy |
| `backend/cliff/assessment/parsers/__init__.py` | Registry no longer needed |
| `backend/cliff/assessment/osv_client.py` | Replaced by Trivy DB |
| `backend/cliff/assessment/ghsa_client.py` | Replaced by Trivy DB |
| `tests/test_parsers_*.py` | Tests for deleted parsers |
| `tests/test_osv_client.py` | Tests for deleted client |
| `tests/test_ghsa_client.py` | Tests for deleted client |

### Implementation notes

**ScannerRunner protocol:**
```python
class ScannerRunner(Protocol):
    async def run_trivy(self, target_dir: Path, *, timeout: int = 300) -> TrivyResult: ...
    async def run_semgrep(self, target_dir: Path, *, timeout: int = 300) -> SemgrepResult: ...
    def available_scanners(self) -> list[ScannerInfo]: ...
```

One implementation. No factory-by-environment branching, no runtime fallback, no auto-detection. Per [ADR-0028](../../adr/0028-subprocess-only-scanner-execution.md), introducing a second runner in the future requires a new ADR.

**Subprocess runner invocation pattern (minimal env — no PAT):**
```python
SCANNER_ENV_ALLOW = ("PATH", "HOME", "LANG", "TRIVY_CACHE_DIR", "SEMGREP_RULES_CACHE_DIR")

def _scanner_env() -> dict[str, str]:
    return {k: os.environ[k] for k in SCANNER_ENV_ALLOW if k in os.environ}

cmd = [settings.trivy_binary, "fs", "--format", "json", "--scanners", "vuln,secret", str(target_dir)]
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=PIPE,
    stderr=PIPE,
    env=_scanner_env(),  # GITHUB_PAT and friends deliberately excluded
)
```

**Checksum verification flow (called at `scripts/install-scanners.sh` time AND at first invocation of each scanner):**
```
read pinned {url, sha256} from .scanner-versions
download or locate binary at configured path
compute sha256 of local file
if computed != pinned:
    if CLIFF_SCANNER_CHECKSUM_VERIFY == "strict":  # default
        raise ScannerChecksumMismatch(...)
    else:  # "warn"
        log.warning("scanner checksum mismatch, proceeding anyway: %s", ...)
```

The Docker image build runs the same verification at `docker build` time (see Docker changes below) so a bad checksum fails the build rather than shipping.

**TrivyResult model** — parse the Trivy JSON schema. Key fields: `Results[].Vulnerabilities[]` with `VulnerabilityID`, `PkgName`, `InstalledVersion`, `FixedVersion`, `Severity`, `Title`, `Description`. Also `Results[].Secrets[]` for secret scanning.

**SemgrepResult model** — parse the Semgrep JSON schema. Key fields: `results[].check_id`, `results[].path`, `results[].start`, `results[].extra.severity`, `results[].extra.message`.

**clone_repo function:**
```python
async def clone_repo(url: str, pat: str | None, dest: Path) -> Path:
    """Shallow clone a repo. Inserts PAT into HTTPS URL if provided."""
    clone_url = _inject_pat(url, pat) if pat else url
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", clone_url, str(dest),
        stdout=PIPE, stderr=PIPE,
    )
    # ...handle errors...
    return dest
```

### Config

New env vars in `backend/cliff/config.py`:
- `CLIFF_TRIVY_BINARY`: path to the Trivy binary (default: baked-in install path, e.g., `./bin/trivy`)
- `CLIFF_SEMGREP_BINARY`: path to the Semgrep binary (default: baked-in install path, e.g., `./bin/semgrep`)
- `CLIFF_SCANNER_CHECKSUM_VERIFY`: `strict` (default) aborts on mismatch; `warn` logs and proceeds. `strict` is the only sane default for a security tool — `warn` exists solely for air-gapped mirrors where the pinned URL isn't reachable

**Removed** (vs pre-ADR-0028 draft): `CLIFF_SCANNER_RUNNER`, `CLIFF_TRIVY_IMAGE`, `CLIFF_SEMGREP_IMAGE`.

### Tests (write first — TDD)

1. `test_trivy_result_parsing` — parse `fixtures/trivy_output.json` into `TrivyResult`, assert vulnerability count, severity mapping
2. `test_semgrep_result_parsing` — parse `fixtures/semgrep_output.json` into `SemgrepResult`, assert finding count
3. `test_subprocess_runner_env_whitelist` — set `GITHUB_PAT=secret` in the parent env, invoke runner with mocked `create_subprocess_exec`, assert the subprocess env passed to the mock contains `PATH` but NOT `GITHUB_PAT`
4. `test_subprocess_runner_timeout` — stub a process that never exits, assert runner kills it after timeout and raises `ScannerTimeout`
5. `test_checksum_verify_strict_raises_on_mismatch` — pin a known-bad checksum, assert `verify.py` raises `ScannerChecksumMismatch`
6. `test_checksum_verify_warn_mode_proceeds` — same setup with `CLIFF_SCANNER_CHECKSUM_VERIFY=warn`, assert it logs + returns
7. `test_clone_repo_success` — mock git subprocess, verify dest path
8. `test_clone_repo_auth` — verify PAT injection into HTTPS URL
9. `test_clone_repo_failure` — mock git failure, verify error handling

---

## Epic 2: Posture expansion

**Goal:** Posture checks expand from ~7 to 15, organized into 4 categories, with advisory distinction.

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/assessment/posture/__init__.py` | Add category enum, expand check registry from ~5 to 15, add `CheckResult.category` and `CheckResult.kind` (pass/fail/advisory) |

### Files to create

| File | Purpose |
|------|---------|
| `backend/cliff/assessment/posture/ci_supply_chain.py` | New checks: actions pinned to SHA, trusted action sources, workflow trigger scope (advisory) |
| `backend/cliff/assessment/posture/collaborator_hygiene.py` | New checks: stale collaborators, broad team permissions (advisory), default branch permissions |
| `backend/cliff/assessment/posture/code_integrity.py` | New checks: secret scanning enabled, code owners file exists, signed commits (advisory) |
| `tests/test_posture_ci.py` | Tests for CI supply chain checks |
| `tests/test_posture_collaborator.py` | Tests for collaborator checks |
| `tests/test_posture_code_integrity.py` | Tests for code integrity checks |

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/assessment/posture/branch.py` | Rename to fit into "repo configuration" category. Add category field |
| `backend/cliff/assessment/posture/secrets.py` | Move secret-scanning-enabled to code_integrity. Keep secrets-in-code regex here |
| `backend/cliff/assessment/posture/files.py` | Add category fields to existing SECURITY.md / dependabot checks |
| `backend/cliff/assessment/posture/github_api.py` | Extend with new GitHub API calls (actions, collaborators, CODEOWNERS) |

### Posture check inventory (15 total)

| # | Check | Category | Kind | New? |
|---|-------|----------|------|------|
| 1 | Branch protection enabled | Repo configuration | pass/fail | Existing |
| 2 | SECURITY.md exists | Repo configuration | pass/fail | Existing |
| 3 | No secrets in code | Repo configuration | pass/fail | Existing |
| 4 | Dependabot configured | Repo configuration | pass/fail | Existing |
| 5 | Actions pinned to SHA | CI supply chain | pass/fail | **New** |
| 6 | Trusted action sources | CI supply chain | pass/fail | **New** |
| 7 | Workflow trigger scope | CI supply chain | advisory | **New** |
| 8 | No stale collaborators | Collaborator hygiene | pass/fail | **New** |
| 9 | Broad team permissions | Collaborator hygiene | advisory | **New** |
| 10 | Default branch permissions | Collaborator hygiene | pass/fail | **New** |
| 11 | Secret scanning enabled | Code integrity | pass/fail | **New** |
| 12 | Code owners file exists | Code integrity | pass/fail | **New** |
| 13 | Signed commits | Code integrity | advisory | **New** |
| 14 | No committed secrets (Trivy) | Code integrity | pass/fail | **New** (from Trivy secret scan) |
| 15 | Lockfile integrity | Repo configuration | pass/fail | **New** |

### Data model

```python
class PostureCategory(str, Enum):
    CI_SUPPLY_CHAIN = "ci_supply_chain"
    COLLABORATOR_HYGIENE = "collaborator_hygiene"
    CODE_INTEGRITY = "code_integrity"
    REPO_CONFIGURATION = "repo_configuration"

class PostureCheckKind(str, Enum):
    PASS_FAIL = "pass_fail"
    ADVISORY = "advisory"

class PostureCheckResult(BaseModel):
    name: str                           # e.g., "actions_pinned_to_sha"
    display_name: str                   # e.g., "Actions pinned to SHA"
    category: PostureCategory
    kind: PostureCheckKind               # pass_fail | advisory (grade impact)
    passed: bool                         # in-pipeline only — collapses pass/done since the pipeline never produces "done"
    detail: str | None = None
    fixable_by: str | None = None        # generator agent name, e.g., "sha_pinning"
```

> **Note (rev. 2):** the wire-shape `state` field on the dashboard payload (`pass | fail | done | advisory`) is a *projection* computed at API read time, not a property of the pipeline DTO. The check itself only knows pass/fail/advisory. `done` is derived by the dashboard route from the posture finding's `status` + `raw_payload.pull_request.url`. Epic 2 stays simple; the projection lives in Epic 4.

### Tests (write first)

1. `test_actions_pinned_check` — fixture with pinned/unpinned workflow YAML
2. `test_trusted_sources_check` — fixture with trusted/untrusted actions
3. `test_stale_collaborators` — mock GitHub API response
4. `test_code_owners_exists` — fixture with/without CODEOWNERS file
5. `test_advisory_checks_dont_fail_grade` — advisory checks should NOT affect pass count for grade calculation

---

## Epic 3: Assessment engine rewrite

**Goal:** `engine.py` orchestrates clone → Trivy → Semgrep → posture → descriptions, reports dynamic scanner-specific steps, and derives grades from 10 criteria.

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/assessment/engine.py` | **Rewrite.** Replace homebrew parser pipeline with scanner orchestration. Add step-by-step progress reporting. Expand grade calculation to 10 criteria |

### Key changes in engine.py

**Step reporting:**
The engine emits progress via a callback function. Each step has a key, label, state, and optional detail/progress/hint:

```python
@dataclass
class AssessmentStep:
    key: str                    # e.g., "trivy_vuln", "semgrep"
    label: str                  # e.g., "Scanning dependencies with Trivy"
    state: Literal["pending", "running", "done", "skipped"]
    progress_pct: int | None    # 0-100 for running state
    detail: str | None          # e.g., "Checking 312 dependencies..." (running state)
    result_summary: str | None  # e.g., "12 findings" (done state)
    hint: str | None            # e.g., "15 checks" (pending state, when scope is knowable in advance)
```

**Tool identity emission (rev. 2 — design delta):**
Alongside the step list, the engine emits a parallel `tools[]` payload representing scanner identity + state + result counts. Same shape on `/dashboard` and `/assessment/status/{id}`:

```python
@dataclass
class AssessmentToolResult:
    kind: Literal["findings_count", "pass_count"]
    value: int
    text: str  # display-ready ("7 findings", "12 pass")

@dataclass
class AssessmentTool:
    id: str                     # "trivy" | "semgrep" | "posture"
    label: str                  # "Trivy 0.52" | "Semgrep 1.70" | "15 posture checks"
    version: str | None         # "0.52.0" / null for the synthetic posture tool
    icon: str                   # "bug_report" | "code" | "rule"
    state: Literal["pending", "active", "done", "skipped"]
    result: AssessmentToolResult | None  # populated on done; null on pending/active/skipped
```

This deliberately replaces the older parallel `scanner_versions: dict` + `tool_states: list` pair. One canonical identity payload, no drift risk between the two consumers.

Counts are derived by the engine after each scanner finishes:
- Trivy `result.value` = `count(finding) WHERE source_type IN ('trivy', 'trivy-secret') AND assessment_id = X`
- Semgrep `result.value` = `count(finding) WHERE source_type = 'semgrep' AND assessment_id = X`
- Posture `result.value` = `count(finding) WHERE type = 'posture' AND state = 'pass' AND assessment_id = X`

**New pipeline:**
```
1. detect     — scan for lockfiles, config files, language markers
2. clone      — git clone --depth 1 (if scanning remote repo)
3. trivy_vuln — trivy fs --scanners vuln (always)
4. trivy_secret — trivy fs --scanners secret (always)
5. semgrep    — semgrep --json (if available + code files detected)
6. posture    — 15 GitHub API + file checks (always)
7. descriptions — finding-normalizer agent for plain_description (always)
```

Steps 3-5 depend on scanner availability (detection from Epic 1). If a scanner is unavailable, its step is marked `skipped` with a reason.

**Grade recalibration (10 criteria):**

```python
CRITERIA = [
    "security_md_present",          # posture check
    "dependabot_configured",        # posture check
    "no_critical_vulns",            # from Trivy results
    "no_high_vulns",                # from Trivy results (NEW)
    "branch_protection_enabled",    # posture check
    "no_secrets_detected",          # from Trivy secret scan
    "actions_pinned_to_sha",        # posture check (NEW)
    "no_stale_collaborators",       # posture check (NEW)
    "code_owners_exists",           # posture check (NEW)
    "secret_scanning_enabled",      # posture check (NEW)
]

# Grade: A=10, B=8-9, C=6-7, D=4-5, F=0-3
```

**CriteriaSnapshot update:**
The existing `CriteriaSnapshot` Pydantic model (stored as JSON in assessments table) expands from 5 to 10 boolean fields. Old snapshots (with 5 fields) must still be readable — use `Optional` with defaults for new fields.

### DB migration

| File | Changes |
|------|---------|
| `backend/cliff/db/migrations/008a_assessment_tools.sql` | Add `tools_json TEXT NULL` column to `assessment` (stores the rev. 2 `tools[]` payload — identity + state + version + result counts, per Epic 3's `AssessmentTool` dataclass). **Note:** the category/kind columns originally planned for `posture_checks` are dropped — Epic 3b removes the `posture_checks` table entirely, so those fields live on `finding` instead (`category`, `grade_impact`) |

The `tools_json` column stores the canonical `tools[]` payload — example shape:

```json
[
  {"id": "trivy",   "label": "Trivy 0.52",        "version": "0.52.0", "icon": "bug_report", "state": "done", "result": {"kind": "findings_count", "value": 7,  "text": "7 findings"}},
  {"id": "semgrep", "label": "Semgrep 1.70",      "version": "1.70.0", "icon": "code",       "state": "done", "result": {"kind": "findings_count", "value": 3,  "text": "3 findings"}},
  {"id": "posture", "label": "15 posture checks", "version": null,     "icon": "rule",       "state": "done", "result": {"kind": "pass_count",     "value": 12, "text": "12 pass"}}
]
```

This replaces the originally-planned `scanner_versions` column (which was just the version map). The richer payload removes the need for a parallel `tool_states[]` field on the wire — same payload serves both `/dashboard` and `/assessment/status/{id}`.

### Tests (write first)

1. `test_engine_step_reporting` — mock scanners, verify step callbacks fire in order
2. `test_engine_scanner_skipped` — make Semgrep unavailable, verify skip step + assessment still completes
3. `test_grade_calculation_10_criteria` — all combos: 10/10=A, 8-9=B, 6-7=C, 4-5=D, 0-3=F
4. `test_criteria_snapshot_backward_compat` — parse an old 5-field snapshot, verify defaults
5. `test_engine_trivy_failure_is_fatal` — if Trivy fails entirely, assessment fails (not partial)
6. `test_engine_semgrep_failure_is_graceful` — if Semgrep fails, assessment continues

---

## Epic 3b: Unified findings model

**Goal:** Every assessment output — Trivy vulns, Trivy secrets, Semgrep code issues, failing/advisory posture checks — persists to the single `finding` table with a typed `type` column. Deprecates `posture_check` table. Implements ADR-0027.

**Dependency order:** Must land *after* Epic 1 (TrivyResult/SemgrepResult models exist), Epic 2 (PostureCheckResult model exists), Epic 3 (assessment engine is rewritten and *calls* these normalizers). Must land *before* Epic 4 (API reads findings grouped by type).

### Files to create

| File | Purpose |
|------|---------|
| `backend/cliff/db/migrations/009_unified_findings.sql` | Add `type`, `grade_impact`, `category`, `assessment_id` columns to `finding`; UNIQUE index on `(source_type, source_id)`; migrate failing/advisory `posture_check` rows; drop `posture_check` table. **Pre-check step** (executed in application code before running the SQL): abort with a clear error if any `(source_type, source_id)` duplicates exist — do not auto-delete, surface them so the operator decides. The SQL itself runs inside a `BEGIN`/`COMMIT` transaction |
| `backend/cliff/assessment/to_findings.py` | Deterministic mappers: `from_trivy_vulns()`, `from_trivy_secrets()`, `from_semgrep()`, `from_posture()` — all returning `list[FindingCreate]` |
| `tests/test_to_findings_trivy.py` | Round-trip fixtures → `FindingCreate` assertions for dependency + secret types |
| `tests/test_to_findings_semgrep.py` | Fixture → `FindingCreate(type='code', ...)` assertions |
| `tests/test_to_findings_posture.py` | Failing + advisory posture results → `FindingCreate(type='posture', grade_impact=...)` assertions |
| `tests/test_unified_findings_migration.py` | Seed old-schema DB with posture_check rows, run migration, assert rows migrated + table dropped |

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/models/finding.py` | Add `FindingType` literal (`dependency`\|`code`\|`secret`\|`posture`), `FindingGradeImpact` literal (`counts`\|`advisory`). Add `type`, `grade_impact`, `category`, `assessment_id` fields to `FindingCreate`, `FindingUpdate`, `Finding` |
| `backend/cliff/db/repo_finding.py` | Change `create_finding` from `INSERT` to `INSERT ... ON CONFLICT(source_type, source_id) DO UPDATE SET ...`. See **UPSERT preservation table** below for exact column rules. Extend `list_findings` to accept `type: list[str] \| None`, `grade_impact: list[str] \| None`, `assessment_id: str \| None` filters |
| `backend/cliff/assessment/engine.py` | After each scanner step completes, call the matching `to_findings` mapper and persist via `create_finding`. Engine no longer returns findings in-memory via `AssessmentResult.findings` — it persists directly and the dashboard reads from the `finding` table. Also: detect findings that existed in the previous assessment for this repo but are absent now, and set their `status='closed'` (system-closed, with a note in `detail`) |
| `backend/cliff/integrations/normalizer.py` | Prompt update: add `type` to the output schema with default `dependency` for ambiguous payloads. Add one short rule: "If the finding is a hygiene/config issue, use `posture`; if a leaked credential, use `secret`; if a SAST/code pattern, use `code`; otherwise `dependency`." No prompt restructure |
| `backend/cliff/integrations/ingest_worker.py` | Pass `type` through from normalizer output (no logic change, just field plumbing) |
| `backend/cliff/db/dao/posture_check.py` | **Delete.** Callers migrated to `list_findings(type=['posture'], assessment_id=...)` |
| `backend/cliff/models/posture_check.py` | **Delete.** `PostureCheckResult` (the in-pipeline Pydantic result type from Epic 2) stays but lives in `backend/cliff/assessment/posture/__init__.py` — it's a pipeline DTO, not a DB model |

### UPSERT preservation table

When `create_finding` hits a conflict on `(source_type, source_id)`, the following columns are **preserved** (left untouched by the update) and the rest are **refreshed** from the new `FindingCreate`. Claude Code must implement this exactly — getting it wrong either silently overwrites user state or silently stales the scanner signal.

| Column | On conflict | Reason |
|--------|-------------|--------|
| `id` | **Preserve** | Row identity |
| `created_at` | **Preserve** | Historical fact |
| `status` | **Preserve** | User lifecycle state (`triaged`, `in_progress`, etc.) |
| `likely_owner` | **Preserve** | May be user-edited or set by an agent; not worth re-deriving on every scan |
| `plain_description` | **Preserve** | LLM-generated by the finding-normalizer agent (see `normalizer.py` — ~625 input-token cost per call). Must survive rescans |
| `why_this_matters` | **Preserve** | Agent-generated |
| `title` | Refresh | Scanner truth |
| `description` | Refresh | Scanner truth |
| `raw_severity` | Refresh | Scanner truth — CVSS scores evolve |
| `normalized_priority` | Refresh | Derives from raw_severity |
| `raw_payload` | Refresh | Latest scanner payload for evidence |
| `type` | Refresh | Taxonomy — source of truth is the mapper |
| `grade_impact` | Refresh | Taxonomy — source of truth is the mapper |
| `category` | Refresh | Taxonomy — source of truth is the mapper |
| `assessment_id` | Refresh | Points at the latest scan that saw it |
| `asset_id`, `asset_label` | Refresh | Scanner-reported resource identity |
| `updated_at` | Refresh | Always bump on UPDATE branch |

SQLite UPSERT syntax reference:

```sql
INSERT INTO finding (id, source_type, source_id, type, grade_impact, category, ...)
VALUES (:id, :source_type, :source_id, :type, :grade_impact, :category, ...)
ON CONFLICT(source_type, source_id) DO UPDATE SET
    title = excluded.title,
    description = excluded.description,
    raw_severity = excluded.raw_severity,
    normalized_priority = excluded.normalized_priority,
    raw_payload = excluded.raw_payload,
    type = excluded.type,
    grade_impact = excluded.grade_impact,
    category = excluded.category,
    assessment_id = excluded.assessment_id,
    asset_id = excluded.asset_id,
    asset_label = excluded.asset_label,
    updated_at = excluded.updated_at;
-- status, likely_owner, plain_description, why_this_matters, id, created_at
-- intentionally omitted from the SET clause.
```

### Deterministic normalizer contracts

```python
# backend/cliff/assessment/to_findings.py
from pathlib import Path
from cliff.models import FindingCreate
from cliff.assessment.scanners.models import TrivyResult, SemgrepResult
from cliff.assessment.posture import PostureCheckResult


def from_trivy_vulns(
    result: TrivyResult, *, assessment_id: str, repo_url: str
) -> list[FindingCreate]:
    """Trivy vuln-scan results → dependency findings.

    source_id format: `{PkgName}@{InstalledVersion}:{VulnerabilityID}`
    """


def from_trivy_secrets(
    result: TrivyResult, *, assessment_id: str, repo_url: str
) -> list[FindingCreate]:
    """Trivy secret-scan results → secret findings.

    source_id format: `{Target}:{StartLine}:{RuleID}`
    """


def from_semgrep(
    result: SemgrepResult, *, assessment_id: str, repo_url: str
) -> list[FindingCreate]:
    """Semgrep results → code findings.

    source_id format: `{path}:{start.line}:{check_id}`
    """


def from_posture(
    results: list[PostureCheckResult], *, assessment_id: str, repo_url: str
) -> list[FindingCreate]:
    """Failing + advisory posture checks → posture findings. Passing checks
    are *not* emitted (they live in criteria_snapshot).

    source_id format: `{repo_url}:{check_name}`
    source_type: 'cliff-posture' (constant)
    grade_impact: 'advisory' if check.kind == advisory else 'counts'
    category: check.category.value (e.g., 'ci_supply_chain')
    """
```

### source_id conventions (from ADR-0027 §6)

| Type | Format | Example |
|------|--------|---------|
| `dependency` | `{PkgName}@{InstalledVersion}:{VulnID}` | `lodash@4.17.19:CVE-2021-23337` |
| `secret` | `{path}:{startLine}:{RuleID}` | `src/config.js:42:aws-access-key-id` |
| `code` | `{path}:{startLine}:{check_id}` | `app/db.py:88:python.django.security.audit.sqli` |
| `posture` | `{repo_url}:{check_name}` | `github.com/gal/repo:actions_pinned_to_sha` |
| External (LLM) | whatever the scanner provides | `snyk:SNYK-JS-LODASH-567746` |

### Closing stale findings on re-scan

After persistence in `engine.py`, for each **scanner source_type** that ran successfully in *this* assessment, select existing open rows from `finding` where `source_type = X` and `source_id NOT IN (source_ids emitted this run by X)`. Mark those `status='closed'`, append a `system_note` to `raw_payload.system_notes` with the current `assessment_id`. This keeps the badge honest and tells the workspace "you've fixed this one."

**Critical scoping rule — close only what you own:**

- Scope by `source_type`, **not** by `type`. Each producer closes only its own output. Example: if Trivy (`source_type='trivy'`) runs today, it closes its own missing findings but must NOT touch findings with `source_type='snyk'` that were imported externally weeks ago, even though both share `type='dependency'`.
- Trivy secret scan uses `source_type='trivy-secret'`; Trivy vuln scan uses `source_type='trivy'`. These are closed independently — a vuln-only run does not close secret findings.
- First-run guard: if no prior assessment exists for this repo, skip the close pass entirely.

**Scanner must have run successfully.** A `source_type` whose scanner was `skipped`, errored, or returned `unknown` for a posture check this assessment does **not** trigger its close pass. Absence of signal is not evidence of fix — silence from a failing scanner must not be laundered into "closed."

### Backward compat for existing DB

The migration in `009_unified_findings.sql`:
1. Adds columns with defaults (`type='dependency'` for existing rows — correct, since all current findings are dependency-style).
2. Migrates failing/advisory `posture_check` rows as `type='posture'` findings.
3. Drops `posture_check` table.
4. Runs inside a `BEGIN`/`COMMIT` transaction so a failure leaves the DB intact.

### Tests (write first — TDD)

1. `test_from_trivy_vulns_mapping` — fixture Trivy JSON → list of `FindingCreate(type='dependency')` with correct `source_id`, severity mapping, `raw_payload` preserved
2. `test_from_trivy_secrets_mapping` — fixture Trivy secret scan → `type='secret'` with path+line `source_id`
3. `test_from_semgrep_mapping` — fixture Semgrep JSON → `type='code'` with path:line:check_id `source_id`
4. `test_from_posture_filters_passing` — mix of pass/fail/advisory results in, only fail/advisory rows come out
5. `test_from_posture_advisory_grade_impact` — advisory posture check → `grade_impact='advisory'`; fail → `grade_impact='counts'`
6. `test_create_finding_upsert_preserves_status` — insert finding, update user status to `triaged`, re-upsert same `source_type/source_id` — status stays `triaged`, `raw_payload` refreshes
7. `test_list_findings_filter_by_type` — seed 4 types, filter by `type=['posture','code']`, assert correct subset
8. `test_engine_closes_disappeared_findings` — two-run scenario: scan 1 emits dep+secret, scan 2 emits only dep → scan 1's secret findings become `status='closed'`
9. `test_engine_skip_does_not_close` — scanner skipped this run → findings from prior run for that type are NOT closed
10. `test_migration_009_moves_posture_rows` — seed DB with old schema + posture_check rows, run migration, assert rows in `finding` with `type='posture'`, assert `posture_check` table gone
11. `test_llm_normalizer_default_type_is_dependency` — raw Snyk payload through normalizer → `type='dependency'`
12. `test_llm_normalizer_extracts_secret_type` — raw payload with "leaked AWS key" in title → `type='secret'` (validates the one-sentence rule works)
13. `test_trivy_rescan_does_not_close_external_findings` — seed a finding with `source_type='snyk'` + `type='dependency'`, run a Trivy scan that emits different findings, assert the Snyk-ingested finding remains `status='new'` (not `closed`). Validates the source_type scoping of the stale-close rule

### Impact on Epic 4 (API)

Epic 4 must update to:
- `GET /findings` accepts `?type=` filter; **default `type=dependency`** for backward compat with the current frontend.
- `GET /dashboard` reads posture findings via `list_findings(type=['posture'], assessment_id=latest)` grouped by `category` client-side. The `GET /dashboard` response shape from the existing Epic 4 spec does not change.
- Remove `POST /posture/fix/{check_name}` routing by `check_name`; replace with `POST /findings/{finding_id}/fix` that inspects the finding's `source_id`/`title` to decide the generator. This keeps the remediation path uniform across all finding types. *(Adjust Epic 4 accordingly.)*

### Risks

| Risk | Mitigation |
|------|------------|
| UNIQUE constraint breaks existing duplicate rows | Migration pre-check aborts with a clear error listing the duplicate `(source_type, source_id)` pairs. Operator resolves manually — no silent delete. Tested in #10 |
| `system-closed` mis-fires and hides still-broken findings | Two explicit rules: (a) scope by `source_type`, so each producer only closes its own; (b) only close when the scanner actually ran successfully. Tested in #8, #9, #13 |
| LLM normalizer type detection is wrong for edge-case payloads | Default is `dependency`; worst case a secret gets filed as dependency, still visible in Findings page. Non-fatal |
| Existing dashboard code paths read `posture_check` DAO | Epic 3b deletes the DAO; compile-time failures caught immediately. Epic 4 replaces with new query |

---

## Epic 4: API + schema updates

**Goal:** Backend API returns scanner-specific steps, grouped posture data, scanned-by metadata, and 10-criteria grades.

### Files to create

| File | Purpose |
|------|---------|
| `backend/cliff/db/migrations/008b_assessment_summary_seen.sql` | Adds `summary_seen_at TEXT NULL` to the `assessment` table. One-line ALTER. Used to gate the assessment-complete interstitial (Surface 3). Defaults NULL on existing rows so they re-show the interstitial once after upgrade — acceptable, single-user community edition |

### Files to modify

| File | Changes |
|------|---------|
| `backend/cliff/api/routes/assessment.py` | Update `GET /assessment/status/{id}` to return `tools[]` and step `hint` (per Epic 3). Update `GET /assessment/latest` to include `tools[]`, grouped posture with the four-state vocabulary, labeled `criteria[]`, `assessment.{started_at, completed_at, summary_seen_at}`, and `vulnerabilities.by_source`. Add `POST /assessment/{id}/mark-summary-seen` — flips `summary_seen_at` to `now()` if NULL; idempotent on subsequent calls |
| `backend/cliff/api/routes/dashboard.py` | Same response shape as `/assessment/latest` (the dashboard reads the most recent complete assessment). Drop the standalone `scanner_versions` field — `tools[]` is the source of truth |
| `backend/cliff/api/routes/posture.py` → `findings.py` | **Replace** `POST /posture/fix/{check_name}` with `POST /findings/{finding_id}/fix`. The handler inspects the finding's `type` + `source_id` to route to the matching generator (`security_md_generator`, `dependabot_config_generator`, `sha_pinning_generator`, `codeowners_generator`). One endpoint for every finding type, per ADR-0027 |
| `backend/cliff/api/routes/onboarding.py` | Ensure `complete` endpoint triggers the new assessment engine |
| `backend/cliff/db/dao/assessment.py` | Update `CriteriaSnapshot` to map keys → labels at response time (the DB column stays as the 10-bool JSON). Update `set_assessment_result` to write `tools_json` (per AssessmentTool dataclasses above). Add `mark_summary_seen(assessment_id)` helper |
| ~~`backend/cliff/db/dao/posture_check.py`~~ | *Deleted in Epic 3b.* Posture reads go through `list_findings(type=['posture'], assessment_id=latest)` in `repo_finding.py` and project to the four-state shape (see §"Response schema changes" below) |

### Response schema changes

**`GET /assessment/status/{id}` — running assessment:**
```jsonc
{
  "assessment": {
    "id": "asm_...",
    "status": "running",
    "started_at":   "2026-04-25T11:08:00Z",
    "completed_at": null,
    "summary_seen_at": null
  },
  "steps": [
    {"key": "detect",      "label": "Detecting project type",         "state": "done",    "result_summary": "npm + Python"},
    {"key": "trivy_vuln",  "label": "Scanning dependencies with Trivy","state": "running", "progress_pct": 42, "detail": "Checking 312 dependencies across npm and pip ecosystems…"},
    {"key": "trivy_secret","label": "Checking for committed secrets",  "state": "pending"},
    {"key": "semgrep",     "label": "Scanning code with Semgrep",      "state": "pending"},
    {"key": "posture",     "label": "Checking repo posture",           "state": "pending", "hint": "15 checks"},
    {"key": "descriptions","label": "Writing plain-language descriptions", "state": "pending"}
  ],
  "tools": [
    {"id": "trivy",   "label": "Trivy 0.52",        "version": "0.52.0", "icon": "bug_report", "state": "active",  "result": null},
    {"id": "semgrep", "label": "Semgrep 1.70",      "version": "1.70.0", "icon": "code",       "state": "pending", "result": null},
    {"id": "posture", "label": "15 posture checks", "version": null,     "icon": "rule",       "state": "pending", "result": null}
  ]
}
```

**`GET /dashboard` (and `GET /assessment/latest`) — completed assessment:**
```jsonc
{
  "assessment": {
    "id": "asm_...",
    "status": "complete",
    "started_at":   "2026-04-25T11:08:00Z",
    "completed_at": "2026-04-25T11:09:24Z",
    "summary_seen_at": null
  },
  "grade": "B",
  "criteria_met": 8,
  "criteria_total": 10,
  "criteria": [
    {"key": "security_md_present",       "label": "SECURITY.md present",         "met": true},
    {"key": "dependabot_configured",     "label": "Dependabot configured",       "met": true},
    {"key": "no_critical_vulns",         "label": "No critical vulns",           "met": true},
    {"key": "no_high_vulns",             "label": "No high vulns",               "met": false},
    {"key": "branch_protection_enabled", "label": "Branch protection enabled",   "met": true},
    {"key": "no_secrets_detected",       "label": "No committed secrets",        "met": true},
    {"key": "actions_pinned_to_sha",     "label": "CI actions pinned to SHA",    "met": false},
    {"key": "no_stale_collaborators",    "label": "No stale collaborators",      "met": true},
    {"key": "code_owners_exists",        "label": "Code owners file exists",     "met": false},
    {"key": "secret_scanning_enabled",   "label": "Secret scanning enabled",     "met": true}
  ],
  "tools": [
    {"id": "trivy",   "label": "Trivy 0.52",        "version": "0.52.0", "icon": "bug_report", "state": "done", "result": {"kind": "findings_count", "value": 7,  "text": "7 findings"}},
    {"id": "semgrep", "label": "Semgrep 1.70",      "version": "1.70.0", "icon": "code",       "state": "done", "result": {"kind": "findings_count", "value": 3,  "text": "3 findings"}},
    {"id": "posture", "label": "15 posture checks", "version": null,     "icon": "rule",       "state": "done", "result": {"kind": "pass_count",     "value": 12, "text": "12 pass"}}
  ],
  "vulnerabilities": {
    "total": 10,
    "by_severity": {"critical": 0, "high": 2, "medium": 5, "low": 3},
    "by_source":   {"dependency": 7, "code": 3, "secret": 0},
    "tool_credits": ["Trivy", "Semgrep"]
  },
  "posture": {
    "pass_count": 12,
    "total_count": 15,
    "advisory_count": 3,
    "categories": [
      {
        "name": "ci_supply_chain",
        "display_name": "CI supply chain",
        "progress": {"done": 1, "total": 2},
        "checks": [
          {"name": "trusted_action_sources",  "display_name": "Trusted action sources", "category": "ci_supply_chain", "state": "pass",     "grade_impact": "counts"},
          {"name": "actions_pinned_to_sha",   "display_name": "Actions not pinned to SHA", "category": "ci_supply_chain", "state": "fail",     "grade_impact": "counts", "fixable_by": "sha_pinning", "detail": "3 actions reference mutable tags (e.g. actions/checkout@v4). Pinning to a commit SHA prevents a compromised maintainer from pushing malicious code under the same tag."},
          {"name": "workflow_trigger_scope",  "display_name": "Workflow trigger scope", "category": "ci_supply_chain", "state": "advisory", "grade_impact": "advisory"}
        ]
      },
      {
        "name": "code_integrity",
        "display_name": "Code integrity",
        "progress": {"done": 3, "total": 4},
        "checks": [
          {"name": "secret_scanning_enabled", "display_name": "Secret scanning enabled", "category": "code_integrity", "state": "pass", "grade_impact": "counts"},
          {"name": "code_owners_exists",      "display_name": "Code owners file missing", "category": "code_integrity", "state": "fail", "grade_impact": "counts", "fixable_by": "codeowners", "detail": "No CODEOWNERS file found. We can generate one based on your git blame history — you review and merge."},
          {"name": "signed_commits",          "display_name": "Signed commits", "category": "code_integrity", "state": "advisory", "grade_impact": "advisory"},
          {"name": "dependabot_configured",   "display_name": "Dependabot configured", "category": "code_integrity", "state": "done", "grade_impact": "counts", "pr_url": "https://github.com/galanko/cliff-demo/pull/14"},
          {"name": "no_committed_secrets",    "display_name": "No committed secrets", "category": "code_integrity", "state": "pass", "grade_impact": "counts"}
        ]
      }
      // collaborator_hygiene + repo_configuration omitted for brevity
    ]
  },
  "quick_wins": [
    {"finding_id": "f_...", "check_name": "sha_pinning", "label": "Pin actions to SHA", "description": "3 actions use mutable tag references"},
    {"finding_id": "f_...", "check_name": "codeowners", "label": "Generate code owners", "description": "No CODEOWNERS file found"}
  ]
}
```

**Posture-check `state` semantics (rev. 2):**

| State | When | Visual (per design) |
|-------|------|---------------------|
| `pass` | Check ran, passed, no agent involvement | `check_circle` filled, `text-tertiary` |
| `fail` | Check ran, failed; may be `fixable_by` an agent | `cancel` filled, `text-error`, card-style row in `bg-primary-container/30` |
| `done` | Check failed previously; an Cliff agent's PR fixed it. `pr_url` is non-null | `check_circle` filled + right-aligned `Draft PR ↗` link |
| `advisory` | Informational, doesn't count toward grade | `info` outline, `text-on-surface-variant`, right-aligned `advisory` chip |

**Source of truth for `done`:** a posture finding (`type='posture'`) with `status` in (`remediated`, `closed`) AND `raw_payload.pull_request.url` set. The dashboard endpoint projects this state at read time. The `pr_url` field passes through `raw_payload.pull_request.url` directly; nothing to add to the UPSERT preservation table beyond what Epic 3b already specifies.

**`POST /assessment/{id}/mark-summary-seen` — minimal:**
```jsonc
// request: empty body
// response: { "assessment": { "id": "asm_...", "summary_seen_at": "2026-04-25T11:10:00Z" } }
```

Idempotent: subsequent calls return the same `summary_seen_at` without rewriting it. Frontend hits this from the "View your report card" CTA on Surface 3.

### New generator agents

| Agent | Template | Trigger |
|-------|----------|---------|
| `sha_pinning_generator` | `.opencode/agents/sha_pinning_generator.md` | `POST /posture/fix/sha_pinning` |
| `codeowners_generator` | `.opencode/agents/codeowners_generator.md` | `POST /posture/fix/codeowners` |

These follow the same pattern as the existing `security_md_generator` and `dependabot_config_generator` from IMPL-0002. Each reads the repo, generates the file, pushes a branch, and opens a draft PR.

### Tests (write first)

1. `test_assessment_status_returns_steps_and_tools` — verify step-by-step response AND `tools[]` shape with state per scanner
2. `test_assessment_status_step_hint_for_posture` — pending posture step renders with `hint: "15 checks"`
3. `test_dashboard_tools_with_results` — completed dashboard returns `tools[]` with `result.text` populated for each (`"7 findings"`, `"3 findings"`, `"12 pass"`)
4. `test_dashboard_grouped_posture_four_state` — verify four-state vocabulary (`pass | fail | done | advisory`); a `done` row carries `pr_url`; an `advisory` row has `grade_impact='advisory'`
5. `test_dashboard_advisory_count_excluded_from_progress` — `posture.categories[].progress.done/total` ignore advisory checks
6. `test_dashboard_criteria_with_labels` — response shape is `criteria: [{key, label, met}]`, length 10; labels match the canonical map
7. `test_dashboard_vulnerabilities_by_source_split` — `code` count equals `count(finding) WHERE type='code'`; `dependency` excludes secrets
8. `test_dashboard_quick_wins_have_finding_id` — every quick-win entry includes the `finding_id` so the frontend can route to `POST /findings/{finding_id}/fix`
9. `test_dashboard_omits_legacy_scanner_versions` — confirm the `scanner_versions` field is gone (catches accidental re-introduction)
10. `test_mark_summary_seen_flips_timestamp` — first call sets `summary_seen_at`; second call returns the same timestamp (idempotent)
11. `test_posture_fix_sha_pinning` — verify endpoint spawns workspace
12. `test_criteria_snapshot_10_fields` — round-trip 10-field snapshot through DB and through the API label projection

---

## Epic 5: Frontend new components

**Goal:** Stand up the new components the Claude design uses. Reference implementations live at `frontend/mockups/claude-design/surfaces/*.jsx` — port to TypeScript + the existing component conventions; do not copy the JSX runtime files in.

### Files to create

| File | Purpose |
|------|---------|
| `frontend/src/components/dashboard/ToolPillBar.tsx` | Row of tool identity pills (pending/active/done/skipped). Each pill: icon + label + optional `result` text. **NEW prop `result?: string`** is the bit Gal flagged — drives the "Trivy 0.52 · 7 findings" rendering on the report card hero |
| `frontend/src/components/dashboard/GradeRing.tsx` | Conic-gradient ring with letter grade in the middle. Sized via `size` prop (72 / 96 / 120 / 192 px in use). Consumes `--p` CSS variable for fill percent (provided by Epic 0's `.grade-ring` class) |
| `frontend/src/components/dashboard/SeverityChip.tsx` | Severity counter chip used on Surface 3 vulns card. Five `kind`s: `critical \| high \| medium \| low \| code`. **Medium uses the `warning` token (ADR-0029)**, not tertiary as the Claude design's reference implementation drew |
| `frontend/src/components/dashboard/CategoryHeader.tsx` | Category eyebrow + done/total numerals + 80px progress rail. Used on Surface 1 |
| `frontend/src/components/dashboard/PostureCategoryGroup.tsx` | Category header + list of `PostureCheckItem` rows. Reads the four-state checks from the dashboard payload |
| `frontend/src/components/dashboard/ScannedByLine.tsx` | "Scanned by" eyebrow + `ToolPillBar` (size `sm`, all `done`, with result counts). Used in the report card hero divider row |
| `frontend/src/components/dashboard/AssessmentSummary.tsx` | Surface 3 interstitial — three summary cards (vulnerabilities / posture / quick wins) + grade preview row + CTA |
| `frontend/src/components/PillButton.tsx` | Primary / ghost / surface variants. Replaces ad-hoc button styling on Surfaces 1–4 |

### Component specifications

**ToolPillBar (rev. 2 — `result` prop is new):**
```tsx
type ToolPillState = 'pending' | 'active' | 'done' | 'skipped';

interface ToolPill {
  id: string;                 // 'trivy' | 'semgrep' | 'posture'
  label: string;              // "Trivy 0.52"
  icon: string;               // Material Symbol name
  state: ToolPillState;
  result?: { text: string };  // NEW. "7 findings" / "12 pass". Rendered as " · {text}" tail.
}

interface ToolPillBarProps {
  tools: ToolPill[];
  size?: 'sm' | 'md';
}
// Backend → frontend mapping: pass dashboardData.tools straight in.
// Active state pulses via Epic 0's .animate-pulse-subtle.
```

**GradeRing:**
```tsx
interface GradeRingProps {
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  percent: number;             // 0..100
  size?: 72 | 96 | 120 | 192;
  sub?: string;                // e.g., "8 of 10"
}
// Renders Epic 0's .grade-ring with --p set inline. Inner cap is bg-surface-container-lowest.
```

**SeverityChip (rev. 2 — medium maps to warning):**
```tsx
interface SeverityChipProps {
  kind: 'critical' | 'high' | 'medium' | 'low' | 'code';
  count: number;
}
// Palette per kind:
//   critical → bg-error-container/40 text-on-error-container
//   high     → bg-error-container/25 text-on-error-container
//   medium   → bg-warning-container/40 text-on-warning-container   <-- ADR-0029, NOT tertiary
//   low      → bg-surface-container-high text-on-surface-variant
//   code     → bg-primary-container/45 text-on-primary-container
```

**CategoryHeader:**
```tsx
interface CategoryHeaderProps {
  title: string;               // "CI supply chain"
  done: number;                // counts pass + done; excludes advisory
  total: number;               // excludes advisory
}
// Renders the eyebrow + "X of Y" numerals + 80px h-1.5 progress rail.
```

**PostureCategoryGroup:**
```tsx
interface PostureCategoryGroupProps {
  category: { name: string; display_name: string; progress: { done: number; total: number }; checks: PostureCheck[] };
}
// Internally renders <CategoryHeader> + a <ul> of PostureCheckItem rows.
```

**`PostureCheckItem` row variants (existing component, reworked):**
The component must render four explicit states from the new `state` field:
- `pass`     → inline row, filled `check_circle`, `text-tertiary`
- `fail`     → card-style row in `bg-primary-container/30`, filled `cancel`, `text-error`. Renders title (semibold) + body. If `fixable_by` is set, primary `PillButton` "Generate {label}" beneath the body, indented to title
- `done`     → inline row, filled `check_circle`, `text-tertiary`, right-aligned `Draft PR ↗` link to `pr_url`
- `advisory` → inline row, outline `info`, `text-on-surface-variant`, right-aligned `advisory` chip in `bg-surface-container-high`

The PRD-0004 four-state pattern (To do / Running / Done / Failed) referenced **for in-flight remediation rows** continues to apply when an agent is actively running for a check — the optimistic flip happens client-side per PRD-0004 Story 3, before the backend confirms the workspace creation.

**AssessmentSummary (Surface 3, variation A picked):**
```tsx
interface AssessmentSummaryProps {
  data: DashboardPayload;        // same shape as /dashboard
  onViewReportCard: () => void;  // POSTs mark-summary-seen + navigates
}
// Three summary cards (vulns / posture / quick wins) + grade preview + CTA.
// Layout: max-w 768px, py-10, gap-6, card p-4.
// Quick-wins card uses bg-primary-container/40 accent.
```

**PillButton:**
```tsx
interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: string;                  // Material Symbol name
  variant?: 'primary' | 'ghost' | 'surface';  // primary = bg-primary, ghost = bg-surface-container-high
  size?: 'sm' | 'md';
}
```

### Design system compliance

All components must follow these rules:
- No `1px solid` borders — use tonal layering
- `text-on-surface` (#2b3437) for text, never #000000
- Manrope for headings, Inter for body
- Google Material Symbols Outlined only (Epic 0's `.msym-filled` for filled variants)
- Sentence case everywhere (the only exception is the 10px uppercase eyebrow / status labels)
- `@media (prefers-reduced-motion: reduce)` is honored via Epic 0's CSS — components add no per-component animation overrides
- Medium severity uses the `warning` token family (ADR-0029); do **not** map medium to `tertiary`

### Tests

Vitest + Testing Library — one test file per component. Each test:
1. Renders default props
2. Walks every `state` / `kind` / `variant` enum value
3. Verifies `aria-label` presence on every non-decorative Material Symbol
4. For `GradeRing`: asserts `--p` is set inline at the requested percent
5. For `ToolPillBar`: asserts the `result.text` tail appears only when `state === 'done'`
6. For `SeverityChip`: asserts `kind='medium'` renders `warning-container` classes (catch the ADR-0029 swap)

---

## Epic 6: Frontend page updates

**Goal:** Wire the new components into existing pages and rebuild the report card hero, completion progress, assessment progress, and onboarding step 3 to match the Claude-design surfaces in `frontend/mockups/claude-design/`.

### Files to modify

| File | Changes |
|------|---------|
| `frontend/src/pages/DashboardPage.tsx` | Rebuild hero per Surface 1: three-column flex (`GradeRing` + narrative + last-assessed/`Re-assess`). Inset `Scanned by` row uses `ScannedByLine`. `CRITERIA_TOTAL` 5→10. Replace flat PostureCard with grouped `PostureCategoryGroup` components (variation A — single tall card with stacked groups). Two-column row below the completion card: `VulnsCard` (380px) + posture card (1fr). Read all data from `dashboardData` — narrative copy is derived client-side from `criteria_met / total` + count of fixable failing posture checks |
| `frontend/src/components/dashboard/AssessmentProgressList.tsx` | Replace 5 hardcoded STEPS with `dashboardData.steps`. Render `ToolPillBar` from `dashboardData.tools`. Active step expands into card-style `bg-primary-container/30` row with progress bar + detail. Pending steps render the optional `hint` chip when present. Add the `Previous assessment` sub-card below — fetched from `/dashboard` (which returns the latest *completed* assessment; the in-progress one comes from `/assessment/status/{id}`). Both queries run in parallel via TanStack Query |
| `frontend/src/components/dashboard/CompletionProgressCard.tsx` | Pill meter → continuous progress bar with 11 ticks (0..10) per Surface 5. Below the bar, render a 2-column `criteria` chip grid using the labeled list from the API. Footer copy: "Reach 10 of 10 to unlock Grade A and the shareable summary." |
| `frontend/src/components/dashboard/PostureCheckItem.tsx` | Reworked into the four state-specific row components (Pass / Fail / Advisory / Done). `GENERATOR_CHECKS` is removed — the `fixable_by` field on the check drives the CTA. Done state renders the `pr_url` link |
| `frontend/src/pages/onboarding/StartAssessment.tsx` | Replace 3 STEPS with 4 (detect → Trivy → posture → descriptions) with explicit time estimates (10s · 60s · 30s · 60s). Add "Powered by" `ToolPillBar` row (all `pending`) inside `bg-surface-container-low rounded-2xl p-4`. Use the exact copy strings from Surface 4 |
| `frontend/src/components/CompletionCelebration/ShareableSummaryCard.tsx` | Replace "5 criteria met" → "10 criteria met". Add "Scanned by: Trivy 0.52 · Semgrep 1.70 · 15 posture checks" line above the Cliff wordmark |
| `frontend/src/api/dashboard.ts` | Update `AssessmentStatusResponse` and `DashboardPayload` types to the rev. 2 schema: `tools[]` (replaces `tool_states[]` and `scanner_versions`), `criteria[]` (labeled list), `vulnerabilities.by_source`, `posture.categories[].progress`, `posture.advisory_count`, posture-check `state` field, `assessment.{started_at, completed_at, summary_seen_at}`, step `hint`. Add `markSummarySeen(assessmentId)` mutation calling `POST /assessment/{id}/mark-summary-seen` |

### Assessment-complete interstitial flow (rev. 2 — server-flag based)

The interstitial is gated by the server's `summary_seen_at` timestamp, not a URL query param.

In `DashboardPage.tsx`:
```tsx
const { data: dashboardData } = useDashboard();
const markSeen = useMarkSummarySeen();

const showInterstitial =
  dashboardData?.assessment?.status === 'complete' &&
  dashboardData?.assessment?.summary_seen_at == null;

if (showInterstitial) {
  return (
    <AssessmentSummary
      data={dashboardData}
      onViewReportCard={() => markSeen.mutate(dashboardData.assessment.id)}
    />
  );
}
```

`markSeen.mutate` POSTs to `/assessment/{id}/mark-summary-seen`, which flips the server flag; the `useDashboard` query invalidates and the next render falls through to the report card. No query-param plumbing, no `firstAssessmentSeen` localStorage.

### Assessment progress + previous assessment

`AssessmentProgressList.tsx` consumes both queries in parallel:
```tsx
const { data: live }      = useAssessmentStatus(runningAssessmentId);   // current run
const { data: previous } = useDashboard({ excludeAssessmentId: live?.assessment?.id });

return (
  <>
    <LiveAssessmentCard
      tools={live?.tools ?? []}
      steps={live?.steps ?? []}
      startedAt={live?.assessment?.started_at}
    />
    {previous?.assessment && <PreviousAssessmentCard data={previous} />}
  </>
);
```

The `excludeAssessmentId` query param is a small new addition to `/dashboard` — when an assessment is running, the dashboard endpoint returns the latest *prior* completed assessment. Cheap (one WHERE clause) and keeps the previous-assessment card honest.

### Tests

1. `test_dashboard_shows_summary_when_unseen` — `summary_seen_at: null` on a complete assessment renders `<AssessmentSummary>`; clicking the CTA fires `markSummarySeen` and falls through to the report card
2. `test_dashboard_shows_report_card_when_seen` — `summary_seen_at: <ts>` skips the interstitial
3. `test_dashboard_renders_tools_with_results_in_hero` — Surface 1's `Scanned by` row shows three pills with the result tail (`"7 findings"`, `"3 findings"`, `"12 pass"`) — guards Gal's flagged behavior
4. `test_dashboard_posture_done_row_links_to_pr` — a posture check with `state='done'` and `pr_url` renders the `Draft PR ↗` link
5. `test_dashboard_completion_card_shows_criteria_chips` — 10 chips with met/unmet styling, sourced from the labeled `criteria[]` array
6. `test_assessment_progress_dynamic_steps_and_tools` — mock API with `tools[]` and steps; verify the active tool pulses, the running step expands into the card-style row, and pending posture step shows the `15 checks` hint
7. `test_assessment_progress_previous_assessment_card` — when an assessment is running, the previous-assessment sub-card renders below the live one
8. `test_onboarding_step3_updated_copy` — verify "Powered by" pill row + 4 step previews + time estimates render
9. `test_severity_chip_medium_uses_warning_token` — `<SeverityChip kind="medium" />` renders `bg-warning-container/40` (catches accidental drift back to tertiary, per ADR-0029)

---

## Cleanup (part of Epic 1)

### Files to delete

All homebrew parser code and advisory clients:

```
backend/cliff/assessment/parsers/          # entire directory
backend/cliff/assessment/osv_client.py
backend/cliff/assessment/ghsa_client.py
tests/test_parsers_npm.py                    # (or whatever the test files are named)
tests/test_parsers_pip.py
tests/test_parsers_golang.py
tests/test_osv_client.py
tests/test_ghsa_client.py
```

Grep for any remaining imports of deleted modules and fix them.

---

## Docker changes

Per [ADR-0028](../../adr/0028-subprocess-only-scanner-execution.md), there is no Docker-in-Docker socket mount. Scanners run as subprocesses inside the Cliff container, from binaries installed at image build time with checksum verification.

### Files to modify

| File | Changes |
|------|---------|
| `docker/Dockerfile` | Add a build step that runs `scripts/install-scanners.sh` (or inlines the equivalent): `curl` the pinned GitHub release URLs from `.scanner-versions`, verify SHA256 against the pinned checksum (fail the build on mismatch), extract to `/opt/cliff/bin/`, `chmod +x`, drop download tarballs. Binaries baked into the image — no runtime download. Final image runs as a non-root user |
| `docker/docker-compose.yml` | **Do NOT add the Docker socket mount.** The earlier draft proposed `-v /var/run/docker.sock:/var/run/docker.sock:ro` for "scanner isolation" — ADR-0028 §"What ADR-0026 got wrong" explains why this is strictly worse than subprocess execution. If any stale reference to socket mounting exists (in compose files, docs, or comments), remove it |

---

## Test plan summary

| Epic | Unit tests | What they cover |
|------|-----------|-----------------|
| 0 | ~3 tests | CSS utilities import wired in `main.tsx`; `.spinner` and `.animate-pulse-subtle` apply animation; `.grade-ring` produces a conic-gradient |
| 1 | ~9 tests | Scanner model parsing, subprocess env whitelist, timeout, checksum verification (strict + warn), clone (success/auth/failure) |
| 2 | ~5 tests | Each new posture check category, advisory distinction |
| 3 | ~7 tests | Engine step reporting (incl. step `hint`), `tools[]` emission with state + result counts, grade calc, backward compat, failure modes |
| 3b | ~13 tests | Deterministic normalizers for 4 types, upsert idempotency + preservation, stale-close scoping by source_type, migration pre-check, LLM type extraction |
| 4 | ~12 tests | Rev. 2 schema (`tools[]`, four-state posture, labeled criteria, `vulnerabilities.by_source`, `mark-summary-seen` idempotency), absence of legacy `scanner_versions`, quick-wins carry `finding_id` |
| 5 | ~7 tests | New components in each state (`ToolPillBar` w/ `result`, `GradeRing`, `SeverityChip` incl. medium-uses-warning, `CategoryHeader`, four PostureRow variants, `AssessmentSummary`) |
| 6 | ~9 tests | Page integration: server-flag interstitial gating, scanner-pill `result` tail rendering, posture done-row PR link, completion-criteria chip grid, dynamic steps + previous-assessment card, onboarding step 3 copy, severity-chip medium uses warning |
| **Total** | **~65 tests** | |

All tests must be written BEFORE implementation (TDD). Run `cd backend && uv run pytest -v` and `cd frontend && npm test` after each epic.

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Trivy JSON schema changes between versions | Low | Pin to specific version. Parse with lenient Pydantic models (extra fields ignored) |
| Compromised scanner release (re-pushed tarball at the pinned URL) | Low | SHA256 pin is per-checksum, not per-version — a re-pushed binary would fail verification. Release process for Cliff regenerates and reviews `.scanner-versions` diffs. See ADR-0028 |
| Scanner binary compromised post-install executes Cliff-user code | Low / bounded | Subprocess runs with minimal env (no PAT), as non-root. Blast radius is bounded to the repo clone + SQLite DB, which is strictly less than the Docker-socket alternative ADR-0026 proposed. Accepted trade |
| GitHub API rate limits during posture checks | Medium | Use conditional requests (ETags). Cache within a single assessment run. PAT increases rate limit from 60 to 5000/hr |
| Large repos slow clone + scan | Medium | Shallow clone (`--depth 1`). Trivy supports `--timeout`. Semgrep supports `--timeout` |
| Old 5-criteria assessment snapshots in DB | Low | New fields have `Optional` defaults. Grade recalculation uses `max(old_count, new_count)` for backward compat |

---

## Implementation order for Claude Code

When Claude Code picks this up, it should:

1. Create a feature branch: `feat/prd-0003-assessment-v2`
2. Work through epics in order: **Epic 0 → 1 → 2 → 3 → 3b → 4 → 5 → 6**. Epic 0 (design tokens / CSS utilities) blocks Epic 5 because the new components reference its keyframes
3. Run tests after each epic — all must pass before proceeding
4. After all epics: run full test suite (`backend pytest` + `frontend npm test` + `ruff check`)
5. Verify the visual fidelity by opening `frontend/mockups/claude-design/PRD-0003 design.html` side-by-side with the running app for each surface
6. Create PR targeting `main`

**Critical: do NOT merge. CEO reviews and merges.**
