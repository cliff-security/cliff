"""EF-B16 regression: POST /api/workspaces { repo_url } must win over the
GitHub integration's snapshot, but omitting it must fall back (backwards-compat).

Bug: the handler at ``backend/cliff/api/routes/workspaces.py`` called
``_resolve_github_repo_url(db)`` unconditionally — ``body.repo_url`` was
declared on ``WorkspaceCreate`` and accepted by FastAPI, but silently dropped
before reaching ``context_builder.create_workspace``.
"""

from __future__ import annotations

import pytest

from cliff.agents.template_engine import AgentTemplateEngine
from cliff.db.connection import get_db
from cliff.db.repo_integration import create_integration
from cliff.db.repo_workspace import get_workspace
from cliff.models import IntegrationConfigCreate
from cliff.workspace.context_builder import WorkspaceContextBuilder
from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_builder(db_client, tmp_path):
    """Swap the conftest mock for a REAL WorkspaceContextBuilder rooted at
    ``tmp_path`` so ``create_workspace`` actually persists ``repo_url`` and
    writes agent templates we can grep.
    """
    from cliff.main import app

    dir_manager = WorkspaceDirManager(base_dir=tmp_path)
    template_engine = AgentTemplateEngine()
    real = WorkspaceContextBuilder(dir_manager, template_engine, mcp_resolver=None)
    app.state.context_builder = real
    yield real


async def _configure_github_integration(repo_url: str) -> None:
    """Insert an enabled GitHub integration carrying the given repo_url."""
    async for db in get_db():
        await create_integration(
            db,
            IntegrationConfigCreate(
                adapter_type="finding_source",
                provider_name="github",
                enabled=True,
                config={"repo_url": repo_url},
            ),
        )
        break


async def _create_finding(db_client, source_id: str = "ef-b16-1") -> str:
    resp = await db_client.post(
        "/api/findings",
        json={
            "source_type": "test",
            "source_id": source_id,
            "title": "EF-B16 test finding",
        },
    )
    return resp.json()["id"]


async def test_explicit_repo_url_overrides_integration_snapshot(
    db_client, real_builder, tmp_path
):
    """AC1+AC3: explicit body.repo_url wins; rendered agent templates
    reference the explicit target, not the integration default."""
    await _configure_github_integration("https://github.com/global/default")
    finding_id = await _create_finding(db_client)

    resp = await db_client.post(
        "/api/workspaces",
        json={
            "finding_id": finding_id,
            "repo_url": "https://github.com/explicit/target",
        },
    )
    assert resp.status_code == 201, resp.text
    workspace_id = resp.json()["id"]

    async for db in get_db():
        ws = await get_workspace(db, workspace_id)
        break
    assert ws is not None
    assert ws.repo_url == "https://github.com/explicit/target"

    agents_dir = tmp_path / workspace_id / ".opencode" / "agents"
    evidence_md = (agents_dir / "evidence_collector.md").read_text()
    assert "explicit/target" in evidence_md
    assert "global/default" not in evidence_md


async def test_omitted_repo_url_falls_back_to_integration(db_client, real_builder):
    """AC2: backwards-compat — omitting body.repo_url inherits the GitHub
    integration's repo_url snapshot."""
    await _configure_github_integration("https://github.com/global/default")
    finding_id = await _create_finding(db_client, source_id="ef-b16-2")

    resp = await db_client.post(
        "/api/workspaces", json={"finding_id": finding_id}
    )
    assert resp.status_code == 201, resp.text
    workspace_id = resp.json()["id"]

    async for db in get_db():
        ws = await get_workspace(db, workspace_id)
        break
    assert ws is not None
    assert ws.repo_url == "https://github.com/global/default"
