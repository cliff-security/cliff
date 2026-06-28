"""The triage run path (IMPL-0024 V1-4) — scanner orchestration.

``run_triage`` reuses the workspace agent-execution machinery: for a scanner
finding it runs enricher → exposure (via the injected executor), then the
deterministic synthesizer, dual-persisting the verdict to the chat timeline (a
``triage_synthesizer`` agent_run card) and ``sidebar.triage``.

Tested with a stub executor that seeds agent_run rows with canned structured
output, so the path runs keyless (no LLM) — the report-triager branch is
covered in M3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cliff.agents.triage_runner import run_triage
from cliff.db.connection import close_db, init_db
from cliff.db.repo_agent_run import (
    create_agent_run,
    list_agent_runs,
    update_agent_run,
)
from cliff.db.repo_finding import create_finding, get_finding
from cliff.db.repo_sidebar import get_sidebar
from cliff.db.repo_workspace import create_workspace
from cliff.models import AgentRunCreate, AgentRunUpdate, FindingCreate, WorkspaceCreate


class _StubExecutor:
    """Simulates ``AgentExecutor.execute`` by writing a completed agent_run
    row with canned structured output for each agent type."""

    def __init__(
        self,
        outputs: dict[str, dict],
        *,
        fail: set[str] | None = None,
        statuses: dict[str, str] | None = None,
    ):
        self.outputs = outputs
        self.fail = fail or set()
        self.statuses = statuses or {}
        self.calls: list[str] = []

    async def check_not_busy(self, db, workspace_id):  # noqa: ANN001
        return None

    async def execute(self, workspace_id, agent_type, db, **_kwargs):  # noqa: ANN001
        self.calls.append(agent_type)
        if agent_type in self.statuses:
            result_status = self.statuses[agent_type]
        elif agent_type in self.fail:
            result_status = "failed"
        else:
            result_status = "completed"
        # The DB run status enum is narrower than the AgentExecutionResult status
        # enum (`awaiting_permission` is result-only), so persist a valid DB state
        # and surface the requested status on the returned result.
        db_valid = ("completed", "failed", "rate_limited")
        db_status = result_status if result_status in db_valid else "running"
        run = await create_agent_run(
            db, workspace_id, AgentRunCreate(agent_type=agent_type, status="running")
        )
        await update_agent_run(
            db,
            run.id,
            AgentRunUpdate(
                status=db_status,
                structured_output=self.outputs.get(agent_type, {}),
            ),
        )
        return SimpleNamespace(status=result_status)


async def _make_workspace(
    db, *, source_type: str = "trivy", finding_type: str = "dependency"
) -> object:
    finding = await create_finding(
        db,
        FindingCreate(
            source_type=source_type,
            source_id="vuln-001",
            title="CVE-2026-0001 in libfoo",
            type=finding_type,
        ),
    )
    ws = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))
    # Give it a directory so the function mirrors the real call shape.
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET workspace_dir = ?, updated_at = ? WHERE id = ?",
        (f"/tmp/ws/{ws.id}", now, ws.id),
    )
    await db.commit()
    return finding, ws


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


_ENRICH_REAL = {
    "normalized_title": "RCE in libfoo",
    "cve_ids": ["CVE-2026-0001"],
    "cvss_score": 9.1,
    "known_exploits": False,
}
_EXPOSURE_REAL = {
    "reachable": "Reachable from the public upload API",
    "internet_facing": True,
    "reachability_evidence": "upload() → parse() → deserialize()",
}
_EXPOSURE_NOPATH = {
    "reachable": "No path found from any entrypoint",
    "internet_facing": False,
}


async def test_scanner_triage_writes_sidebar_and_chat_card(db) -> None:
    _finding, ws = await _make_workspace(db)
    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )

    triage = await run_triage(executor, db, ws, env_vars={})

    assert triage is not None
    assert triage.verdict == "real"
    # Ran the scanner pipeline in order.
    assert executor.calls == ["finding_enricher", "exposure_analyzer"]
    # Sidebar persisted.
    sidebar = await get_sidebar(db, ws.id)
    assert sidebar is not None and sidebar.triage is not None
    assert sidebar.triage["verdict"] == "real"
    # Chat timeline card persisted (dual-persist rule).
    runs = await list_agent_runs(db, ws.id)
    synth = [r for r in runs if r.agent_type == "triage_synthesizer"]
    assert len(synth) == 1
    assert synth[0].status == "completed"
    assert synth[0].structured_output["verdict"] == "real"
    assert synth[0].summary_markdown  # a human-readable verdict line


async def test_triage_rerun_overwrites_sidebar_verdict(db) -> None:
    _finding, ws = await _make_workspace(db)
    first = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )
    await run_triage(first, db, ws, env_vars={})
    second = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_NOPATH}
    )
    triage = await run_triage(second, db, ws, env_vars={})

    assert triage is not None and triage.verdict == "unexploitable"
    sidebar = await get_sidebar(db, ws.id)
    assert sidebar.triage["verdict"] == "unexploitable"


async def test_triage_does_not_advance_finding_status(db) -> None:
    """Triage keeps the finding `new` — status only advances on human
    confirmation of a `real` verdict (the gate)."""
    finding, ws = await _make_workspace(db)
    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )
    await run_triage(executor, db, ws, env_vars={})
    refreshed = await get_finding(db, finding.id)
    assert refreshed.status == "new"


async def test_failed_exposure_degrades_to_needs_review(db) -> None:
    """A failed prerequisite (e.g. the exposure agent timing out) must NOT abort
    triage with no verdict — that strands the CLI on a poll-timeout (exit 1) and
    leaves a dead UI. It degrades to a `needs_review` verdict, landed in both the
    sidebar and the chat card. Never a silent clear; never a crash."""
    _finding, ws = await _make_workspace(db)
    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL}, fail={"exposure_analyzer"}
    )
    triage = await run_triage(executor, db, ws, env_vars={})
    assert triage is not None
    assert triage.verdict == "needs_review"  # never a clear, never None
    sidebar = await get_sidebar(db, ws.id)
    assert sidebar is not None and sidebar.triage is not None
    assert sidebar.triage["verdict"] == "needs_review"


async def test_prereq_failure_ignores_stale_prior_runs(db) -> None:
    """A failed prerequisite must degrade to needs_review even when a PRIOR
    successful exposure run (confident, real-looking) lingers in the workspace.
    `list_latest_runs` would otherwise hand that stale output to the synthesizer
    and project a confident `real` on a failed triage — never synthesize a
    verdict from stale data."""
    _finding, ws = await _make_workspace(db)
    # Seed a stale, confident-looking exposure run from a prior attempt.
    prior = await create_agent_run(
        db, ws.id, AgentRunCreate(agent_type="exposure_analyzer", status="running")
    )
    await update_agent_run(
        db, prior.id, AgentRunUpdate(status="completed", structured_output=_EXPOSURE_REAL)
    )
    # This attempt's enricher fails → the loop breaks before a fresh exposure run,
    # leaving the stale one as the latest.
    executor = _StubExecutor({}, fail={"finding_enricher"})
    triage = await run_triage(executor, db, ws, env_vars={})
    assert triage is not None
    assert triage.verdict == "needs_review"  # NOT `real` from the stale exposure


async def test_non_completed_prereq_status_degrades(db) -> None:
    """Only a `completed` prerequisite may proceed. A non-completed, non-failed
    status (e.g. `awaiting_permission`) must also degrade — even if that run
    recorded a confident, real-looking output that ``list_latest_runs`` (which
    doesn't filter by status) would otherwise hand to the synthesizer."""
    _finding, ws = await _make_workspace(db)
    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL},
        statuses={"exposure_analyzer": "awaiting_permission"},
    )
    triage = await run_triage(executor, db, ws, env_vars={})
    assert triage is not None
    assert triage.verdict == "needs_review"  # NOT `real` from the un-completed run


async def test_code_finding_defers_to_needs_review(db) -> None:
    """A code/SAST finding the exposure analyzer flagged as reachable+facing must
    NOT ship as a confident `real` from the quick read — `run_triage` threads
    `finding.type` so the synthesizer defers it to needs_review (→ Deep dive)."""
    _finding, ws = await _make_workspace(db, source_type="semgrep", finding_type="code")
    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )
    triage = await run_triage(executor, db, ws, env_vars={})
    assert triage is not None
    assert triage.verdict == "needs_review"  # deferred, not the dependency `real`


async def test_codemap_gate_clears_and_skips_deep_dive(monkeypatch, db) -> None:
    """When the repo code_map marks the finding's path non-ship, run_triage returns
    false_positive WITHOUT invoking the Deep dive."""
    import cliff.agents.triage_runner as tr

    async def _fake_load_code_map(db, repo_url):  # noqa: ANN001
        return {"classified": [{"glob": "tests/**", "category": "test", "reason": "suite"}]}

    called = {"deep": False}

    async def _fake_deep(*a, **k):  # noqa: ANN002, ANN003
        called["deep"] = True
        return None

    monkeypatch.setattr(tr, "_load_code_map", _fake_load_code_map)
    monkeypatch.setattr(tr, "maybe_deep_dive", _fake_deep)

    # Arrange: finding with path in tests/, workspace with repo_url.
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="vuln-gate-001",
            title="CVE-2026-0001 in libfoo",
            type="dependency",
            raw_payload={"path": "tests/test_x.py"},
        ),
    )
    ws = await create_workspace(
        db, WorkspaceCreate(finding_id=finding.id, repo_url="https://github.com/test/repo")
    )
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET workspace_dir = ?, updated_at = ? WHERE id = ?",
        (f"/tmp/ws/{ws.id}", now, ws.id),
    )
    await db.commit()

    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )

    triage = await run_triage(executor, db, ws, env_vars={})

    assert triage is not None
    assert triage.verdict == "false_positive"
    assert called["deep"] is False
    # The cleared verdict must be dual-persisted (chat card + sidebar), not just
    # returned — the CLAUDE.md agent-output rule applies to the gate's verdict too.
    sidebar = await get_sidebar(db, ws.id)
    assert sidebar is not None and sidebar.triage is not None
    assert sidebar.triage["verdict"] == "false_positive"
    runs = await list_agent_runs(db, ws.id)
    synth = [r for r in runs if r.agent_type == "triage_synthesizer"]
    assert len(synth) == 1 and synth[0].structured_output["verdict"] == "false_positive"


async def test_codemap_gate_no_match_runs_deep_dive(monkeypatch, db) -> None:
    """When nothing matches, the Deep dive still runs (gate is transparent)."""
    import cliff.agents.triage_runner as tr
    from cliff.agents.schemas import TriageOutput

    async def _fake_load_code_map(db, repo_url):  # noqa: ANN001
        return {"classified": [{"glob": "tests/**", "category": "test", "reason": "s"}]}

    monkeypatch.setattr(tr, "_load_code_map", _fake_load_code_map)

    _deep_sentinel = TriageOutput(verdict="real", confidence=0.99)

    async def _fake_deep(*a, **k):  # noqa: ANN002, ANN003
        return _deep_sentinel

    monkeypatch.setattr(tr, "maybe_deep_dive", _fake_deep)

    # Arrange: finding with path in src/ (no match for tests/**).
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="vuln-gate-002",
            title="CVE-2026-0001 in libfoo",
            type="dependency",
            raw_payload={"path": "src/app.py"},
        ),
    )
    ws = await create_workspace(
        db, WorkspaceCreate(finding_id=finding.id, repo_url="https://github.com/test/repo")
    )
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET workspace_dir = ?, updated_at = ? WHERE id = ?",
        (f"/tmp/ws/{ws.id}", now, ws.id),
    )
    await db.commit()

    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )

    triage = await run_triage(executor, db, ws, env_vars={})

    assert triage is not None
    assert triage is _deep_sentinel
    # The deep-dive verdict must also be dual-persisted, so a dropped
    # _persist_synthesis on this branch can't pass the return-value check alone.
    sidebar = await get_sidebar(db, ws.id)
    assert sidebar is not None and sidebar.triage is not None
    assert sidebar.triage["verdict"] == "real"


# ---------------------------------------------------------------------------
# _load_code_map robustness: corrupt / unreadable / non-dict code_map
# ---------------------------------------------------------------------------


async def test_load_code_map_returns_none_when_read_artifact_raises(monkeypatch, db) -> None:
    """If read_artifact raises (e.g. corrupt/unreadable JSON), _load_code_map
    returns None — the gate falls through to the Deep dive; triage never crashes."""
    import cliff.agents.triage_runner as tr

    # Patch the name bound in triage_runner's namespace (imported via
    # `from cliff.repos.dao import get_repo_by_url`); patching repos_dao directly
    # would leave the triage_runner binding untouched and skip the early-return.
    async def _fake_get_repo(db, url):  # noqa: ANN001
        return SimpleNamespace(id="repo-1", profile_status="ready")

    monkeypatch.setattr(tr, "get_repo_by_url", _fake_get_repo)

    # Make the dir manager's read_artifact raise on any call.
    class _BrokenDirManager:
        def read_artifact(self, repo_id, name):  # noqa: ANN001
            raise OSError("disk read error")

    monkeypatch.setattr(tr, "default_repo_dir_manager", lambda: _BrokenDirManager())

    result = await tr._load_code_map(db, "https://github.com/test/repo")
    assert result is None


async def test_load_code_map_returns_none_for_non_dict_artifact(monkeypatch, db) -> None:
    """If read_artifact returns a non-dict JSON value (list, string, None),
    _load_code_map returns None so the gate falls through safely."""
    import cliff.agents.triage_runner as tr

    # Patch the name bound in triage_runner's namespace so the repo-status guard
    # is actually exercised and the read_artifact branch is reached.
    async def _fake_get_repo(db, url):  # noqa: ANN001
        return SimpleNamespace(id="repo-1", profile_status="ready")

    monkeypatch.setattr(tr, "get_repo_by_url", _fake_get_repo)

    for bad_value in ([], "string", 42, None):
        # Capture `bad_value` in the default arg to avoid the B023 late-binding
        # pitfall: without the default, all iterations would see the last value.
        class _BadDirManager:
            def read_artifact(self, repo_id, name, _val=bad_value):  # noqa: ANN001
                return _val

        monkeypatch.setattr(tr, "default_repo_dir_manager", lambda: _BadDirManager())

        result = await tr._load_code_map(db, "https://github.com/test/repo")
        assert result is None, f"expected None for bad_value={bad_value!r}, got {result!r}"


async def test_codemap_gate_falls_through_on_corrupt_code_map(monkeypatch, db) -> None:
    """When _load_code_map returns None (corrupt/unreadable), run_triage must
    NOT crash — it falls through to the Deep dive / quick verdict path."""
    import cliff.agents.triage_runner as tr

    async def _load_raises(db, repo_url):  # noqa: ANN001
        return None  # simulates corrupt code_map already returning None

    monkeypatch.setattr(tr, "_load_code_map", _load_raises)

    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="vuln-corrupt-001",
            title="CVE-2026-0001 in libfoo",
            type="dependency",
            raw_payload={"path": "tests/test_x.py"},
        ),
    )
    ws = await create_workspace(
        db, WorkspaceCreate(finding_id=finding.id, repo_url="https://github.com/test/repo")
    )
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET workspace_dir = ?, updated_at = ? WHERE id = ?",
        (f"/tmp/ws/{ws.id}", now, ws.id),
    )
    await db.commit()

    executor = _StubExecutor(
        {"finding_enricher": _ENRICH_REAL, "exposure_analyzer": _EXPOSURE_REAL}
    )

    # Must not raise — falls through to quick read / deep dive (no deep dive configured
    # here, so lands the quick verdict).
    triage = await run_triage(executor, db, ws, env_vars={})
    assert triage is not None
    # verdict is NOT false_positive (gate was skipped)
    assert triage.verdict != "false_positive"
