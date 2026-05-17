# Session B → Session A/G — Inter-session contract gaps

**Surfaced:** 2026-04-16 during architect review of PR #54 (Session B).
**Status:** Two of three gaps validated clean against Session A's merged code; the third is real and must be fixed in Session G.
**Scope:** three places where Session B's merged implementation assumes Session A behaves a specific way, and the original session prompts did not lock that down. Sessions A–F are already running concurrently; rather than chasing their prompts mid-flight, this doc captures the contracts Session G will verify and fix with a small adapter if needed.

## Validation results (2026-04-16, post-merge)

After all seven Sessions 0/A–F PRs landed on `main`, each gap was validated against the integrated tree:

| Gap | Result | Evidence |
|-----|--------|----------|
| **#1 — DAO-write ownership** | ✅ **clean** | `git grep 'from cliff.db.dao' backend/cliff/assessment/` returns zero matches. Session A's orchestrator never calls a DAO. |
| **#2 — Posture-check dict shape** | ✅ **clean** | `backend/cliff/assessment/engine.py` returns `[pc.model_dump() for pc in posture_checks]` where `PostureCheck.check_name` and `PostureCheck.status` are `Literal` types matching exactly what `_background.py::run_and_persist_assessment` reads via `check["check_name"]` / `check["status"]`. |
| **#3 — Findings persistence path** | ✅ **resolved in Session G** | The Gap #3 loop landed in `backend/cliff/api/_background.py::run_and_persist_assessment` on branch `feat/from-zero-to-secure-integration`. Regression covered by `tests/api/test_assessment_routes.py::test_run_assessment_persists_findings_emitted_by_engine`. Engine-emitted findings are tagged `source_type='cliff-assessment'` so the dashboard can distinguish them from vendor imports. |

Session G's first action item (I0) closes Gap #3 by adding the loop in `_background.py::run_and_persist_assessment`.



## Context

Session B's DI seam (`backend/cliff/api/_engine_dep.py`) declares `AssessmentEngineProtocol.run_assessment(repo_url, *, assessment_id) -> AssessmentResult`. Session B's background coroutine (`backend/cliff/api/_background.py::run_and_persist_assessment`) then drives that protocol and writes every output to the DB.

The protocol return type is `AssessmentResult`, which was frozen in Session 0 as:

```python
class AssessmentResult(BaseModel):
    assessment_id: str
    repo_url: str
    grade: Grade
    criteria_snapshot: CriteriaSnapshot
    findings: list[dict[str, Any]] = []
    posture_checks: list[dict[str, Any]] = []
```

The `list[dict[str, Any]]` typing leaves the inner item shapes unspecified. Session B reads them with specific key names; if Session A emits different keys the integration silently breaks.

## Gap 1 — DAO-write ownership

**Session B's assumption:** the engine **returns** results; the route owns every DAO write. Session B's `run_and_persist_assessment` calls `upsert_posture_check` and `set_assessment_result` on the engine's return value; if the engine also wrote those rows, we'd double-write.

**IMPL-0002 Milestone B6 wording:** "writes `assessments` + `posture_checks` rows, emits `FindingCreate` list for the ingest pipeline."

**Gap:** the plan says "writes rows"; Session B's implementation interprets "writes rows" as "hands the data to Session B to write." Session A might import `cliff.db.dao.assessment` and call `set_assessment_result` itself — causing double-writes, or overwriting the `pending → running → complete` status transitions Session B is driving.

**Session G validation (I0):**
- `grep -R 'from cliff.db.dao' backend/cliff/assessment/` must return zero matches.
- Run one end-to-end assessment and assert only one row per `assessment_id` in `assessment` and one per `(assessment_id, check_name)` in `posture_check`.

**Fix if Session A did import DAOs:** strip the writes out of Session A's orchestrator (one-line deletes per row) rather than disabling Session B's writer — Session B's writer owns status transitions and completion-row creation, which Session A's orchestrator doesn't know about.

---

## Gap 2 — Posture-check dict shape

**Session B's assumption:** `AssessmentResult.posture_checks` items have keys `check_name` (str matching `PostureCheckName`), `status` (`"pass"|"fail"|"advisory"|"unknown"`), and optionally `detail` (dict or None). This matches `PostureCheckCreate` minus `assessment_id`. See `_background.py` lines 56–65.

**Gap:** the frozen `list[dict[str, Any]]` typing doesn't enforce this. Session A could emit `{"name": "...", "result": "pass"}` and pass pyright.

**Session G validation:**
- Add one real engine run in the integration test; after the run, assert `posture_check` rows exist with non-null `check_name` / `status` values. If they're null or missing, the key names don't match.

**Fix if Session A used different keys:** two options:
1. **Preferred**: patch Session A's orchestrator to use the expected keys (`check_name`, `status`, `detail`) — it's a rename, not a design change.
2. **If Session A has shipped already and a rename is costly**: add a small adapter in `_background.py::run_and_persist_assessment` that maps whatever keys Session A used to what `PostureCheckCreate` expects. Prefer option 1 — option 2 creates a hidden translation layer nobody reads.

---

## Gap 3 — Findings persistence path

**Session B's assumption:** the `findings` field on `AssessmentResult` is informational only. `run_and_persist_assessment` does **not** iterate `result.findings` — Session A is responsible for persisting each finding itself via the ingest pipeline (`repo_ingest_job.create_ingest_job` for batches, or `repo_finding.create_finding` synchronously).

**IMPL-0002 Milestone B6 wording:** "emits `FindingCreate` list for the ingest pipeline."

**Gap:** "emits" is ambiguous. Session A could:
- (a) populate `AssessmentResult.findings` and expect Session B to persist them (Session B will NOT do this — silent data loss), OR
- (b) push findings into the ingest pipeline itself and leave `AssessmentResult.findings` empty (what Session B expects).

**Session G validation:**
- After a real end-to-end run, assert `SELECT COUNT(*) FROM finding WHERE source_type = 'cliff-assessment'` returns the expected count for the fixture repo.
- Assert `len(result.findings) == 0` from Session A's engine, or at least that whatever's in it is a duplicate of what's already in the DB.

**Fix if Session A populated `result.findings` instead:** add a single loop in `_background.py::run_and_persist_assessment`:

```python
for finding_data in result.findings:
    await create_finding(db, FindingCreate(**finding_data, source_type="cliff-assessment"))
```

Position it after the posture-check loop, before `set_assessment_result`. Add the `source_type` default so frontend filters can distinguish engine-emitted findings from vendor-imported ones.

---

## Why this lives in known-issues, not in session prompts

Sessions A–F are already running concurrently as of the Session B merge. Changing Session A's prompt mid-flight would not help — the running session won't re-read it. Session G is the last session and hasn't started; it's the natural place to validate these contracts and patch whichever way reality diverged from Session B's assumptions.

If a future multi-session execution plan surfaces the same class of ambiguity again (typed-but-loose dict payloads crossing session boundaries), the fix is to tighten the Pydantic model in the contracts-freeze session, not to patch prompts after the fact. The Session 0 stub for `AssessmentResult.posture_checks` and `AssessmentResult.findings` as `list[dict[str, Any]]` is the true root cause — typed `list[PostureCheckPayload]` / `list[FindingCreate]` in the contracts freeze would have made all three of these gaps impossible.

## Checklist for Session G

- [x] Grep Session A's tree for `from cliff.db.dao` imports — must be empty. _(Validated 2026-04-16 post-merge — clean.)_
- [x] Apply the Gap #3 fix-path: add the `for finding_data in result.findings` loop in `_background.py::run_and_persist_assessment` immediately after the posture-check loop. Pass `source_type="cliff-assessment"` so dashboard filters can distinguish engine-emitted findings from vendor-imported ones. _(Landed in Session G PR against `feat/from-zero-to-secure-integration`.)_
- [x] Run a real end-to-end assessment against a fixture repo with known posture gaps and planted vulns. _(Covered by `tests/api/test_integration_engine.py` using `ProductionAssessmentEngine` with the planted-repo `clone_strategy` seam.)_
- [x] Assert exactly one `assessment` row, one row per unique `check_name` in `posture_check`, and the expected number of `finding` rows with `source_type='cliff-assessment'`.
- [x] Resolved by Session G PR on branch `feat/from-zero-to-secure-integration`.
