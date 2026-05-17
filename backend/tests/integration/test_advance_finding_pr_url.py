"""EF-B14 — executor success path must persist pr_url onto Finding.

Without this, a user who closes the workspace before the close-handler's
reconciliation pass runs would lose the link entirely.
"""

from __future__ import annotations

from opensec.agents.executor import _advance_finding_status
from opensec.db.repo_finding import create_finding, get_finding
from opensec.db.repo_workspace import create_workspace
from opensec.models import FindingCreate, WorkspaceCreate

PR_URL = "https://github.com/cliff-security/NodeGoat/pull/6"


async def test_advance_finding_status_persists_pr_url_on_executor_success(db) -> None:
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="fsevents@1.2.9:CVE-2023-45311",
            title="Code injection in fsevents",
            status="in_progress",
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))

    structured = {"status": "pr_created", "pr_url": PR_URL}
    new_status = await _advance_finding_status(
        db, workspace.id, "remediation_executor", structured
    )

    assert new_status == "remediated"
    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.status == "remediated"
    assert after.pr_url == PR_URL


async def test_advance_finding_status_preserves_existing_pr_url(db) -> None:
    """Don't clobber a user-supplied pr_url set via PATCH /findings/{id}."""
    user_url = "https://github.com/example/repo/pull/42"
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="x",
            title="x",
            status="in_progress",
            pr_url=user_url,
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))

    structured = {"status": "pr_created", "pr_url": PR_URL}
    await _advance_finding_status(
        db, workspace.id, "remediation_executor", structured
    )

    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.pr_url == user_url


async def test_advance_finding_status_skips_pr_url_when_not_pr_created(db) -> None:
    """Executor reported a different status (e.g. 'failed'); don't write a
    bogus pr_url from a non-success payload."""
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="y",
            title="y",
            status="in_progress",
        ),
    )
    workspace = await create_workspace(db, WorkspaceCreate(finding_id=finding.id))

    structured = {"status": "failed", "pr_url": None}
    new_status = await _advance_finding_status(
        db, workspace.id, "remediation_executor", structured
    )

    assert new_status is None
    after = await get_finding(db, finding.id)
    assert after is not None
    assert after.pr_url is None
