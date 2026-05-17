# Assessment Engine

The assessment engine is the deterministic Python module that turns a cloned
repo into a grade. It lives under [backend/cliff/assessment/](../../backend/cliff/assessment/)
and has no LLM, no DB writes, and no inbound dependencies on the API layer —
it's a pure pipeline:

```
RepoCloner ──► parsers/ ──► osv_client/ghsa_client ──► posture/ ──► engine.derive_grade
                                                                     │
                                                      AssessmentResult emitted here
```

The API layer (`backend/cliff/api/_background.py`) drives the engine via the
`AssessmentEngineProtocol` DI seam and persists every output it emits. The
engine never touches the DB directly — that invariant is covered by
`backend/tests/api/test_integration_engine.py`.

## Where things live

| Concern | Files |
|---|---|
| Public orchestrator | [backend/cliff/assessment/engine.py](../../backend/cliff/assessment/engine.py) |
| Production entry point (shallow clone + real clients) | [backend/cliff/assessment/production_engine.py](../../backend/cliff/assessment/production_engine.py) |
| Lockfile parsers | [backend/cliff/assessment/parsers/](../../backend/cliff/assessment/parsers/) (npm, pip, go — one module each) |
| OSV + GHSA clients | `osv_client.py`, `ghsa_client.py` |
| Posture checks | [backend/cliff/assessment/posture/](../../backend/cliff/assessment/posture/) (files, branch, secrets, github_client) |
| Unit tests | [backend/tests/assessment/](../../backend/tests/assessment/) |
| Integration test (real engine vs mocked clients + planted fixture) | [backend/tests/api/test_integration_engine.py](../../backend/tests/api/test_integration_engine.py) |
| Lockfile fixtures | [backend/tests/fixtures/lockfiles/](../../backend/tests/fixtures/lockfiles/) |
| OSV response fixtures | [backend/tests/fixtures/osv/](../../backend/tests/fixtures/osv/) |

## Adding a new lockfile parser

The registry is a simple tuple of `(ecosystem, filename, callable)` entries
in `parsers/__init__.py`. To add e.g. a Ruby `Gemfile.lock` parser:

1. **Add a fixture first** — drop a `Gemfile.lock` with a known-vulnerable
   dep under `backend/tests/fixtures/lockfiles/ruby/`.
2. **Write the failing test** at `backend/tests/assessment/parsers/test_ruby_parser.py`:
   ```python
   def test_ruby_parser_extracts_every_dep_with_version() -> None:
       deps = parse_gemfile_lock(Path("tests/fixtures/lockfiles/ruby/Gemfile.lock"))
       assert any(d.name == "nokogiri" and d.version == "1.13.0" for d in deps)
   ```
3. **Implement** `backend/cliff/assessment/parsers/ruby.py` returning
   `list[ParsedDependency]`. Match the existing parsers' shape — constructor
   takes a `Path`, caller handles exceptions (one malformed lockfile must
   not kill the run, per the `_collect_dependencies` contract in `engine.py`).
4. **Register** the parser in `parsers/__init__.py::detect_lockfiles` by
   appending to the `_REGISTRY` list:
   ```python
   ("ruby", "Gemfile.lock", parse_gemfile_lock),
   ```
5. **Run** `uv run pytest tests/assessment/ -v` — the orchestrator test in
   `test_engine.py` will pick up the new parser automatically on any
   fixture that includes a `Gemfile.lock`.

See also: `docs/architecture/plans/IMPL-0002-earn-the-badge.md` Milestone B
(npm, pip, go ship in v1.1; ruby/java/rust/yarn are follow-up PRs with no
schema change).

## Adding a new posture check

Posture checks implement a simple shape: `(repo_path, gh_client, coords) ->
PostureCheckResult`. They're composed in `posture/__init__.py::run_all_posture_checks`.

1. **Extend the literal** in [backend/cliff/models/posture_check.py](../../backend/cliff/models/posture_check.py):
   add your check name to `PostureCheckName`.
2. **Write the failing test** at `backend/tests/assessment/posture/test_your_check.py`.
   Use `tmp_path` to plant whatever the check looks for (a file, a commit
   log shape, etc.). For GitHub-backed checks, mock `gh_client` with
   `unittest.mock.AsyncMock`.
3. **Implement** under `backend/cliff/assessment/posture/`. Return a
   `PostureCheckResult(check_name=..., status="pass|fail|advisory|unknown", detail=...)`.
4. **Register** in `run_all_posture_checks` so it runs on every assessment.
   Order matters only for output stability — tests should not depend on it.
5. **Decide the grade effect** in `engine.py::derive_grade`. Only the five
   criteria listed there influence the letter grade; other checks show up
   in the dashboard but don't move the grade needle. This is deliberate —
   per ADR-0025 the five criteria are the contract with the user.
6. **Render in the UI** — extend [frontend/src/components/dashboard/PostureCheckItem.tsx](../../frontend/src/components/dashboard/PostureCheckItem.tsx)
   if your check needs a different failure affordance (e.g. a "Generate
   fix PR" button). The generic `pass` / `advisory` states need no change.

## Running the engine locally

For quick iteration on a parser or posture check, drive `run_assessment_on_path`
directly — no git clone, no DB:

```python
import asyncio, httpx
from pathlib import Path
from cliff.assessment.engine import run_assessment_on_path
from cliff.assessment.osv_client import OsvClient
from cliff.assessment.posture.github_client import GithubClient

async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        result = await run_assessment_on_path(
            Path("/tmp/some/cloned/repo"),
            repo_url="https://github.com/owner/repo",
            gh_client=GithubClient(http, token=None),
            osv=OsvClient(http),
        )
    print(result.grade, len(result.findings), "findings")

asyncio.run(main())
```

For production-like runs (shallow clone + temp dir + token), use
`ProductionAssessmentEngine.run_assessment(repo_url, assessment_id=...)`.

## Running the integration tests

```bash
cd backend && uv run pytest tests/assessment/ tests/api/test_integration_engine.py -v
```

The integration test uses the same `clone_strategy` hook the Playwright E2E
uses — it copies a planted fixture directory into the engine's tmp clone
location and wires `httpx.MockTransport` for OSV/GitHub. No network.

## Running the E2E suite

```bash
cd frontend
npx playwright install --with-deps   # one-time
npx playwright test                  # all three browsers
npx playwright test --project=chromium
```

Playwright boots the backend on port 18000 and the Vite dev server on 15173
(deliberately offset from the developer defaults so the E2E never collides
with a running `scripts/dev.sh`). The backend is configured via env vars:

- `CLIFF_TEST_FIXTURE_REPO_DIR` — path to the planted repo fixture
  ([frontend/tests/e2e/fixtures/repo/](../../frontend/tests/e2e/fixtures/repo/))
- `CLIFF_TEST_FIXTURE_OSV_DIR` — path to OSV response JSON files keyed
  by `<ecosystem>_<package>_<version>.json`
  ([frontend/tests/e2e/fixtures/osv/](../../frontend/tests/e2e/fixtures/osv/))

When both are set, `get_assessment_engine()` swaps in a fixture-backed
`ProductionAssessmentEngine` that copies from the fixture dir instead of
invoking `git clone` and replays OSV/GitHub responses from the JSON files.
See [backend/cliff/assessment/_test_seam.py](../../backend/cliff/assessment/_test_seam.py).

## Error semantics

* Any network failure (OSV, GHSA, GitHub) degrades the affected check to
  `UnableToVerify` — assessments never fail on a flaky dependency.
* One malformed lockfile is logged and skipped; the assessment continues
  with the remaining files.
* An engine-level exception (git clone timeout, KeyboardInterrupt, etc.)
  bubbles out of `run_and_persist_assessment` and flips the assessment row
  to `status="failed"`. The background task's exception handler in
  [_background.py](../../backend/cliff/api/_background.py) catches
  everything — the API response has already returned by that point.
