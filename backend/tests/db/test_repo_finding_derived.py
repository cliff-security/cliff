"""Tests for IMPL-0006 T2 — ``Finding.derived`` composition + batch helpers.

Asserts:

1. ``list_findings`` populates ``derived`` on every row.
2. ``get_finding`` populates ``derived`` on a single read.
3. ``derived`` reflects the workspace + sidebar + agent-run state correctly.
4. **N+1 guard** — listing 100 findings issues at most 4 read queries beyond
   the base ``SELECT * FROM finding``: workspaces, agent runs, sidebars.
"""

from __future__ import annotations

from cliff.db.repo_agent_run import (
    create_agent_run,
    list_latest_runs_by_workspace_ids,
)
from cliff.db.repo_finding import (
    create_finding,
    get_finding,
    list_findings,
    mark_resolved_on_workspace_close,
    mark_started_on_workspace_create,
    update_finding,
)
from cliff.db.repo_sidebar import (
    list_sidebars_by_workspace_ids,
    upsert_sidebar,
)
from cliff.db.repo_workspace import (
    create_workspace,
    list_workspaces_by_finding_ids,
)
from cliff.models import (
    AgentRunCreate,
    FindingCreate,
    FindingUpdate,
    SidebarStateUpdate,
    WorkspaceCreate,
)

# ----------------------------------------------------------------------------
# Batch helpers
# ----------------------------------------------------------------------------


async def test_list_workspaces_by_finding_ids_returns_one_per_finding(db) -> None:
    f1 = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a")
    )
    f2 = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="b", title="b")
    )
    w1 = await create_workspace(db, WorkspaceCreate(finding_id=f1.id))
    w2 = await create_workspace(db, WorkspaceCreate(finding_id=f2.id))

    by_finding = await list_workspaces_by_finding_ids(db, [f1.id, f2.id])

    assert by_finding[f1.id].id == w1.id
    assert by_finding[f2.id].id == w2.id


async def test_list_workspaces_by_finding_ids_empty_input_returns_empty(db) -> None:
    assert await list_workspaces_by_finding_ids(db, []) == {}


async def test_list_workspaces_by_finding_ids_picks_most_recent_when_dup(db) -> None:
    f1 = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a")
    )
    older = await create_workspace(db, WorkspaceCreate(finding_id=f1.id))
    newer = await create_workspace(db, WorkspaceCreate(finding_id=f1.id))

    by_finding = await list_workspaces_by_finding_ids(db, [f1.id])

    assert by_finding[f1.id].id == newer.id
    assert older.id != newer.id


async def test_list_latest_runs_returns_keyed_by_workspace_and_type(db) -> None:
    f = await create_finding(db, FindingCreate(source_type="trivy", source_id="a", title="a"))
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))

    older = await create_agent_run(
        db, w.id, AgentRunCreate(agent_type="remediation_planner", status="completed")
    )
    newer = await create_agent_run(
        db, w.id, AgentRunCreate(agent_type="remediation_planner", status="running")
    )
    other = await create_agent_run(
        db, w.id, AgentRunCreate(agent_type="remediation_executor", status="running")
    )

    by_ws = await list_latest_runs_by_workspace_ids(db, [w.id])

    assert by_ws[w.id]["remediation_planner"].id == newer.id
    assert by_ws[w.id]["remediation_executor"].id == other.id
    assert older.id != newer.id


async def test_list_sidebars_returns_keyed_by_workspace(db) -> None:
    f = await create_finding(db, FindingCreate(source_type="trivy", source_id="a", title="a"))
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
    await upsert_sidebar(db, w.id, SidebarStateUpdate(plan={"steps": [{"title": "x"}]}))

    by_ws = await list_sidebars_by_workspace_ids(db, [w.id])

    assert by_ws[w.id].plan == {"steps": [{"title": "x"}]}


# ----------------------------------------------------------------------------
# derived population on list_findings + get_finding
# ----------------------------------------------------------------------------


async def test_list_findings_populates_derived_for_finding_without_workspace(db) -> None:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a")
    )

    findings = await list_findings(db)

    assert len(findings) == 1
    assert findings[0].id == f.id
    assert findings[0].derived is not None
    assert findings[0].derived.section == "todo"
    assert findings[0].derived.stage == "todo"
    assert findings[0].derived.workspace_id is None


async def test_list_findings_populates_derived_for_review_plan_ready(db) -> None:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a")
    )
    await update_finding(db, f.id, FindingUpdate(status="in_progress"))
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
    await upsert_sidebar(
        db, w.id, SidebarStateUpdate(plan={"steps": [{"title": "Bump dep"}]})
    )

    findings = await list_findings(db)

    assert findings[0].derived is not None
    assert findings[0].derived.section == "review"
    assert findings[0].derived.stage == "plan_ready"
    assert findings[0].derived.workspace_id == w.id


async def test_get_finding_populates_derived(db) -> None:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a")
    )
    await update_finding(db, f.id, FindingUpdate(status="in_progress"))
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
    await upsert_sidebar(
        db,
        w.id,
        SidebarStateUpdate(
            pull_request={"status": "pr_created", "pr_url": "https://x/y/pull/1"}
        ),
    )

    found = await get_finding(db, f.id)

    assert found is not None
    assert found.derived is not None
    assert found.derived.section == "review"
    assert found.derived.stage == "pr_ready"
    assert found.derived.pr_url == "https://x/y/pull/1"


# ----------------------------------------------------------------------------
# mark_started_on_workspace_create
# ----------------------------------------------------------------------------


async def test_mark_started_flips_new_to_in_progress(db) -> None:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="a", title="a", status="new")
    )
    flipped = await mark_started_on_workspace_create(db, f.id)
    assert flipped is True
    refreshed = await get_finding(db, f.id)
    assert refreshed is not None
    assert refreshed.status == "in_progress"


async def test_mark_started_flips_triaged_to_in_progress(db) -> None:
    f = await create_finding(
        db,
        FindingCreate(
            source_type="trivy", source_id="a", title="a", status="triaged"
        ),
    )
    assert await mark_started_on_workspace_create(db, f.id) is True
    refreshed = await get_finding(db, f.id)
    assert refreshed is not None
    assert refreshed.status == "in_progress"


async def test_mark_started_leaves_other_statuses_alone(db) -> None:
    """Closed / remediated / validated / exception rows must NOT be silently
    re-opened by a workspace re-creation."""
    for status in ("in_progress", "remediated", "validated", "closed", "exception"):
        f = await create_finding(
            db,
            FindingCreate(
                source_type="trivy",
                source_id=f"item-{status}",
                title=status,
                status=status,
            ),
        )
        flipped = await mark_started_on_workspace_create(db, f.id)
        assert flipped is False, f"{status} should be left alone"
        refreshed = await get_finding(db, f.id)
        assert refreshed is not None
        assert refreshed.status == status


# ----------------------------------------------------------------------------
# mark_resolved_on_workspace_close
# ----------------------------------------------------------------------------


async def test_mark_resolved_flips_in_progress_to_validated(db) -> None:
    f = await create_finding(
        db,
        FindingCreate(
            source_type="trivy", source_id="a", title="a", status="in_progress"
        ),
    )
    flipped = await mark_resolved_on_workspace_close(db, f.id)
    assert flipped is True
    refreshed = await get_finding(db, f.id)
    assert refreshed is not None
    assert refreshed.status == "validated"


async def test_mark_resolved_flips_remediated_to_validated(db) -> None:
    """Most common path — agent opened a PR, user merged it, validator hadn't
    run yet; user clicks Resolve in the workspace."""
    f = await create_finding(
        db,
        FindingCreate(
            source_type="trivy", source_id="a", title="a", status="remediated"
        ),
    )
    assert await mark_resolved_on_workspace_close(db, f.id) is True
    refreshed = await get_finding(db, f.id)
    assert refreshed is not None
    assert refreshed.status == "validated"


async def test_mark_resolved_flips_new_and_triaged_too(db) -> None:
    """Defensive — user explicitly chose Resolve, even on a workspace that
    never started agents. Honour the click."""
    for status in ("new", "triaged"):
        f = await create_finding(
            db,
            FindingCreate(
                source_type="trivy",
                source_id=f"item-{status}",
                title=status,
                status=status,
            ),
        )
        assert await mark_resolved_on_workspace_close(db, f.id) is True
        refreshed = await get_finding(db, f.id)
        assert refreshed is not None
        assert refreshed.status == "validated"


async def test_mark_resolved_leaves_terminal_statuses_alone(db) -> None:
    """Already-Done findings (validated / closed / exception / passed) must
    not be silently re-categorised."""
    for status in ("validated", "closed", "exception", "passed"):
        f = await create_finding(
            db,
            FindingCreate(
                source_type="trivy",
                source_id=f"item-{status}",
                title=status,
                status=status,
            ),
        )
        flipped = await mark_resolved_on_workspace_close(db, f.id)
        assert flipped is False, f"{status} should be left alone"
        refreshed = await get_finding(db, f.id)
        assert refreshed is not None
        assert refreshed.status == status


# ----------------------------------------------------------------------------
# N+1 guard
# ----------------------------------------------------------------------------


class _QueryCounter:
    """Wraps an aiosqlite connection's ``execute`` to count SELECTs.

    Only counts read queries (statements starting with ``SELECT``); ignores
    ``INSERT`` / ``UPDATE`` / ``COMMIT``. SQLite's PRAGMA chatter (``PRAGMA``)
    is also excluded so the count reflects derivation queries, not bookkeeping.
    """

    def __init__(self, conn) -> None:
        self.conn = conn
        self.count = 0
        self._original_execute = conn.execute

    async def execute(self, sql, params=None):
        normalized = sql.strip().lstrip("(").lstrip().upper()
        if normalized.startswith("SELECT"):
            self.count += 1
        if params is None:
            return await self._original_execute(sql)
        return await self._original_execute(sql, params)

    def __enter__(self):
        self.conn.execute = self.execute
        return self

    def __exit__(self, *a):
        self.conn.execute = self._original_execute


async def test_list_findings_n_plus_1_guard_at_100_findings(db) -> None:
    # Create 100 findings, half with workspaces + sidebars + a running agent run.
    for i in range(100):
        f = await create_finding(
            db,
            FindingCreate(source_type="trivy", source_id=f"item-{i}", title=f"item {i}"),
        )
        if i % 2 == 0:
            await update_finding(db, f.id, FindingUpdate(status="in_progress"))
            w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
            await upsert_sidebar(
                db, w.id, SidebarStateUpdate(plan={"steps": [{"title": "x"}]})
            )
            await create_agent_run(
                db,
                w.id,
                AgentRunCreate(agent_type="remediation_planner", status="completed"),
            )

    with _QueryCounter(db) as counter:
        findings = await list_findings(db, limit=200)

    assert len(findings) == 100
    # 1 SELECT findings + 1 SELECT workspaces + 1 SELECT agent_runs + 1 SELECT
    # sidebars = 4 max. Anything more is an N+1.
    assert counter.count <= 4, (
        f"N+1 regression — list_findings issued {counter.count} SELECTs, expected ≤ 4"
    )

    # Spot-check derived was actually composed.
    by_id = {f.id: f for f in findings}
    review_rows = [f for f in findings if f.derived and f.derived.section == "review"]
    todo_rows = [f for f in findings if f.derived and f.derived.section == "todo"]
    assert len(review_rows) == 50
    assert len(todo_rows) == 50
    assert all(f.derived is not None for f in by_id.values())
