"""EF-B14 regression — close handler must reconcile pr_url back to Finding.

Reproduces the QA-0001 fsevents scenario: executor opens a real PR (recorded
in AgentRun.structured_output), user calls cliffsec close (PATCH /workspaces
state=closed), and the Finding silently lands in status=validated with
pr_url=null — leaving the PR orphaned and the dashboard lying about closure.
"""

from __future__ import annotations

import logging

from cliff.db.repo_agent_run import create_agent_run, update_agent_run
from cliff.db.repo_finding import (
    create_finding,
    get_finding,
    mark_resolved_on_workspace_close,
)
from cliff.db.repo_workspace import create_workspace
from cliff.models import (
    AgentRunCreate,
    AgentRunUpdate,
    FindingCreate,
    WorkspaceCreate,
)

PR_URL = "https://github.com/cliff-security/NodeGoat/pull/6"


async def _seed_executor_run(db, workspace_id: str, *, pr_url: str | None) -> None:
    run = await create_agent_run(
        db,
        workspace_id,
        AgentRunCreate(agent_type="remediation_executor"),
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            status="completed",
            summary_markdown="opened pr",
            confidence=0.9,
            structured_output={"status": "pr_created", "pr_url": pr_url},
        ),
    )


async def test_close_auto_populates_pr_url_from_latest_executor_run(db) -> None:
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="fsevents@1.2.9:CVE-2023-45311",
            title="Code injection in fsevents",
            status="remediated",
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))
    await _seed_executor_run(db, workspace.id, pr_url=PR_URL)

    flipped = await mark_resolved_on_workspace_close(
        db, finding.id, workspace_id=workspace.id
    )

    assert flipped is True
    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.status == "validated"
    assert after.pr_url == PR_URL, (
        "Close handler must reconcile pr_url from the latest executor run "
        "instead of silently leaving the finding with pr_url=null."
    )


async def test_close_leaves_pr_url_null_when_no_executor_run_exists(db) -> None:
    """Posture findings with no autofix template never run the executor;
    closing them with pr_url=null is correct."""
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="checkov",
            source_id="POSTURE_001",
            title="Posture finding",
            status="in_progress",
            type="posture",
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))

    flipped = await mark_resolved_on_workspace_close(
        db, finding.id, workspace_id=workspace.id
    )

    assert flipped is True
    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.status == "validated"
    assert after.pr_url is None


async def test_close_warns_when_executor_ran_but_pr_url_missing(db, caplog) -> None:
    """fsevents-style case: executor was attempted (failed/timeout) but
    structured_output never received pr_url. We can't recover the URL — but
    we must NOT silently close. Emit a WARNING so reviewers see it."""
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="fsevents@1.2.9:CVE-2023-45311",
            title="Code injection in fsevents",
            status="remediated",
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))
    run = await create_agent_run(
        db,
        workspace.id,
        AgentRunCreate(agent_type="remediation_executor"),
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(status="failed", summary_markdown="Agent timed out."),
    )

    with caplog.at_level(logging.WARNING, logger="cliff.db.repo_finding"):
        flipped = await mark_resolved_on_workspace_close(
            db, finding.id, workspace_id=workspace.id
        )

    assert flipped is True
    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.pr_url is None
    assert any(
        "pr_url could not be reconciled" in rec.message.lower()
        for rec in caplog.records
    ), "must log a WARNING so reviewers can spot orphaned PRs post-hoc"
