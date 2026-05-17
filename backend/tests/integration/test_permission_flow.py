"""End-to-end-ish integration test for the agent-permission approval gate.

Exercises the full backend loop with a real in-memory DB and a fake
OpenCode client that streams a synthetic ``permission_request`` event:

  1. The executor parks a ``_PendingApproval`` for the ask-tier command.
  2. The agent_run row gets ``permission_pending=1`` + the request JSON.
  3. The user POSTs to ``/.../permission`` (simulated by calling the
     executor's ``approve_tool`` / ``deny_tool`` directly — the route
     test in test_routes_agent_execution covers the HTTP edge).
  4. The asyncio event resolves, the marker clears, and the executor
     calls grant/deny on the fake client.
  5. After the run ends, ``derive()`` routes the finding via the new
     stage as long as the row carries the marker (we assert by reading
     a snapshot of the row at the pending moment).

The integration test deliberately mocks ONLY the OpenCode client; the
DB, the executor, the repo, and ``derive()`` are all real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensec.agents.executor import AgentExecutor
from opensec.db.repo_agent_run import get_agent_run, list_agent_runs
from opensec.db.repo_finding import create_finding, update_finding
from opensec.db.repo_workspace import create_workspace
from opensec.models import FindingCreate, FindingUpdate, WorkspaceCreate
from opensec.models.issue_derivation import derive

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor_response() -> str:
    return (
        "```json\n"
        '{"summary": "ran the patch",'
        '"result_card_markdown": "ok",'
        '"structured_output": {"status": "changes_made", "pr_url": null,'
        '"branch_name": "opensec/fix/x", "changes_summary": "patched",'
        '"test_results": "pass", "error_details": null},'
        '"confidence": 0.9, "evidence_sources": [],'
        '"suggested_next_action": "open_pr"}\n'
        "```"
    )


class _AskBashStream:
    """A fake OpenCode client whose stream yields one ask-tier permission
    request, waits for it to resolve, then completes."""

    def __init__(self) -> None:
        self.permission_resolved = asyncio.Event()
        self.grant_calls: list[tuple[str, str]] = []
        self.deny_calls: list[tuple[str, str]] = []
        self._session = MagicMock(id="ses-1")
        self.create_session = AsyncMock(return_value=self._session)
        self.send_message = AsyncMock(return_value=None)

    async def grant_permission(self, permission_id: str, *, session_id: str) -> None:
        self.grant_calls.append((permission_id, session_id))
        self.permission_resolved.set()

    async def deny_permission(self, permission_id: str, *, session_id: str) -> None:
        self.deny_calls.append((permission_id, session_id))
        self.permission_resolved.set()

    async def stream_events(self, session_id: str) -> AsyncIterator[dict]:
        yield {
            "type": "permission_request",
            "id": "per_rm",
            "tool": "bash",
            "patterns": ["rm", "-rf", "build/"],
        }
        # The real stream blocks here until grant/deny is invoked; our
        # fake waits on the same signal so the executor can observe the
        # marker mid-flight before we continue with the text/done events.
        await self.permission_resolved.wait()
        yield {"type": "text", "content": _make_executor_response()}
        yield {"type": "done"}


async def _seed_workspace(db) -> tuple[str, str, Path]:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="x", title="x")
    )
    await update_finding(db, f.id, FindingUpdate(status="in_progress"))
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
    workspace_dir = Path("/tmp") / f"perm-ws-{w.id}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "context.json").write_text("{}")
    return f.id, w.id, workspace_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_persists_marker_then_clears_and_resumes_agent(
    db,
) -> None:
    finding_id, workspace_id, workspace_dir = await _seed_workspace(db)

    pool = AsyncMock()
    fake_client = _AskBashStream()
    pool.get_or_start.return_value = fake_client

    builder = AsyncMock()
    builder.update_context.return_value = "v1"
    executor = AgentExecutor(pool, builder)

    # Snapshot the row while the executor is parked.
    snapshot: dict = {}

    async def approve_after_seeing_marker(event_dict: dict) -> None:
        # Poll the DB until the executor has persisted the marker, then
        # capture a snapshot and approve. This proves the marker is
        # visible to derive() WHILE the agent is still parked.
        for _ in range(50):
            await asyncio.sleep(0.01)
            run = await get_agent_run(db, event_dict["run_id"])
            if run is not None and run.permission_pending:
                snapshot["status_during_wait"] = run.status
                snapshot["permission_pending"] = run.permission_pending
                snapshot["permission_request"] = run.permission_request
                break
        executor.approve_tool(event_dict["run_id"])

    def on_perm(event_dict: dict) -> None:
        asyncio.create_task(approve_after_seeing_marker(event_dict))

    with (
        patch("opensec.agents.executor.map_and_upsert", new=AsyncMock()),
        patch(
            "opensec.agents.executor._advance_finding_status",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "opensec.agents.executor._load_workspace_data",
            return_value=({}, {}),
        ),
        patch(
            "opensec.agents.executor.AgentTemplateEngine"
        ) as engine_cls,
    ):
        engine_cls.return_value.render_agent.return_value = MagicMock(
            content="prompt"
        )
        result = await executor.execute(
            workspace_id,
            "remediation_executor",
            db,
            workspace_dir=str(workspace_dir),
            on_permission=on_perm,
        )

    # Snapshot was taken — marker was visible mid-wait.
    assert snapshot["status_during_wait"] == "running"
    assert snapshot["permission_pending"] is True
    assert snapshot["permission_request"] == {
        "id": "per_rm",
        "tool": "bash",
        "patterns": ["rm", "-rf", "build/"],
    }

    # Approve path → grant_permission called.
    assert len(fake_client.grant_calls) == 1
    assert fake_client.grant_calls[0][0] == "per_rm"
    assert fake_client.deny_calls == []

    # Marker cleared on the final row.
    runs = await list_agent_runs(db, workspace_id)
    assert len(runs) == 1
    final = runs[0]
    assert final.permission_pending is False
    assert final.permission_request is None
    assert result.agent_run_id == final.id


@pytest.mark.asyncio
async def test_deny_persists_then_clears_and_denies_to_engine(db) -> None:
    finding_id, workspace_id, workspace_dir = await _seed_workspace(db)

    pool = AsyncMock()
    fake_client = _AskBashStream()
    pool.get_or_start.return_value = fake_client

    builder = AsyncMock()
    builder.update_context.return_value = "v1"
    executor = AgentExecutor(pool, builder)

    async def deny_quickly(event_dict: dict) -> None:
        await asyncio.sleep(0.02)
        executor.deny_tool(event_dict["run_id"])

    def on_perm(event_dict: dict) -> None:
        asyncio.create_task(deny_quickly(event_dict))

    with (
        patch("opensec.agents.executor.map_and_upsert", new=AsyncMock()),
        patch(
            "opensec.agents.executor._advance_finding_status",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "opensec.agents.executor._load_workspace_data",
            return_value=({}, {}),
        ),
        patch(
            "opensec.agents.executor.AgentTemplateEngine"
        ) as engine_cls,
    ):
        engine_cls.return_value.render_agent.return_value = MagicMock(
            content="prompt"
        )
        await executor.execute(
            workspace_id,
            "remediation_executor",
            db,
            workspace_dir=str(workspace_dir),
            on_permission=on_perm,
        )

    assert fake_client.deny_calls == [("per_rm", "ses-1")]
    assert fake_client.grant_calls == []

    runs = await list_agent_runs(db, workspace_id)
    final = runs[0]
    assert final.permission_pending is False
    assert final.permission_request is None


@pytest.mark.asyncio
async def test_derive_routes_to_review_awaiting_permission_when_marker_set(
    db,
) -> None:
    """Mid-wait derive() must surface the finding in review/awaiting_permission.
    We simulate by directly setting the marker on a running run, then calling
    derive() with the same models the API layer would assemble."""
    from opensec.db.repo_agent_run import (
        create_agent_run,
        list_latest_runs_by_workspace_ids,
        update_agent_run,
    )
    from opensec.db.repo_finding import get_finding
    from opensec.db.repo_workspace import list_workspaces_by_finding_ids
    from opensec.models import AgentRunCreate, AgentRunUpdate

    finding_id, workspace_id, _ = await _seed_workspace(db)
    run = await create_agent_run(
        db,
        workspace_id,
        AgentRunCreate(agent_type="remediation_executor", status="running"),
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            permission_pending=True,
            permission_request={
                "id": "per_rm",
                "tool": "bash",
                "patterns": ["rm", "-rf", "build/"],
            },
        ),
    )

    finding = await get_finding(db, finding_id)
    ws_by_finding = await list_workspaces_by_finding_ids(db, [finding_id])
    runs_by_ws = await list_latest_runs_by_workspace_ids(db, [workspace_id])

    result = derive(
        finding,
        workspace=ws_by_finding[finding_id],
        sidebar=None,
        latest_runs_by_type=runs_by_ws[workspace_id],
    )

    assert result.section == "review"
    assert result.stage == "awaiting_permission"
