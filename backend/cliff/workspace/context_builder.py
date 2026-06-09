"""WorkspaceContextBuilder — orchestrates L0 (filesystem) + L1 (templates) + DB metadata."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from cliff.db.repo_finding import mark_started_on_workspace_create
from cliff.db.repo_sidebar import mark_plan_approved as _repo_mark_plan_approved
from cliff.db.repo_workspace import (
    create_workspace,
    delete_workspace,
    get_workspace,
    increment_context_version,
    update_workspace,
    update_workspace_dir,
)
from cliff.models import WorkspaceCreate, WorkspaceUpdate
from cliff.workspace.agent_run_log import AgentRunLog
from cliff.workspace.workspace_dir import AGENT_TYPE_TO_SECTION

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

    from cliff.integrations.gateway import MCPConfigResolver
    from cliff.models import Finding, Workspace
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

logger = logging.getLogger(__name__)


class WorkspaceContextBuilder:
    """Orchestrates workspace lifecycle: directory + context + DB metadata.

    Wraps Layer 0 (WorkspaceDirManager) into a single service that manages
    the full workspace lifecycle — the per-workspace directory holds the
    finding context (finding.json, CONTEXT.md, per-agent context sections)
    the Pydantic AI agents read at run time (ADR-0047).

    All public methods are async (called from FastAPI routes) but delegate
    to synchronous L0/L1 operations directly — filesystem ops are fast local
    I/O and aiosqlite is already the serialization point.
    """

    def __init__(
        self,
        dir_manager: WorkspaceDirManager,
        *,
        mcp_resolver: MCPConfigResolver | None = None,
    ) -> None:
        self._dir_manager = dir_manager
        self._mcp_resolver = mcp_resolver

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_workspace(
        self,
        db: aiosqlite.Connection,
        finding: Finding,
        *,
        initial_focus: str | None = None,
        repo_url: str | None = None,
        advance_status: bool = True,
    ) -> Workspace:
        """Create a complete workspace: DB row + directory + finding context.

        Steps:
            1. Create DB row
            2. Resolve workspace integrations from vault (if configured)
            3. Create directory structure with finding context
            4. Store directory path in DB

        ``repo_url`` is the snapshot of the GitHub integration's repo at the
        moment the workspace was opened (migration 013). Agents prefer this
        over the live integration value so editing the integration mid-flight
        doesn't silently rebind the workspace to a different repo.

        ``advance_status`` flips ``Finding.status`` new/triaged → in_progress
        (the remediation "Start" semantics). Triage passes ``False``: a triage
        run needs the workspace directory + finding context, but must NOT
        advance the finding — it stays ``new`` until a `real` verdict is
        confirmed (ADR-0051 §6, the Plan gate).

        Returns the fully populated Workspace model.
        """
        # 1. DB row
        ws_data = WorkspaceCreate(
            finding_id=finding.id,
            state="open",
            current_focus=initial_focus,
            repo_url=repo_url,
        )
        workspace = await create_workspace(db, ws_data)

        # 1b. Flip Finding.status new/triaged → in_progress so the Issues
        # page (PRD-0006) moves the row out of Todo on the user's click,
        # rather than waiting for the first agent run to update it.
        # Idempotent — other statuses are left alone. Skipped for triage runs
        # (advance_status=False) so the finding stays untriaged until confirmed.
        if advance_status:
            await mark_started_on_workspace_create(db, finding.id)

        # 2. Resolve workspace integrations (if vault is configured) for the
        # manifest agents read for available-tooling context.
        ws_integrations = None
        if self._mcp_resolver is not None:
            try:
                result = await self._mcp_resolver.resolve_workspace(db)
                ws_integrations = result.integrations
            except Exception:
                logger.warning(
                    "Failed to resolve workspace integrations for workspace %s",
                    workspace.id,
                    exc_info=True,
                )

        # 3. Filesystem directory — finding context only (finding.json,
        # finding.md, CONTEXT.md, empty context sections). The PA agents
        # read these at run time (ADR-0047).
        ws_dir = self._dir_manager.create(workspace.id, finding)

        # 3b. Write workspace integrations manifest
        if ws_integrations:
            from dataclasses import asdict

            manifest = [asdict(i) for i in ws_integrations]
            (ws_dir.root / "workspace-integrations.json").write_text(
                json.dumps(manifest, indent=2) + "\n"
            )

        # 4. Store path in DB
        await update_workspace_dir(db, workspace.id, str(ws_dir.root))

        logger.info("Created workspace %s at %s", workspace.id, ws_dir.root)
        return await get_workspace(db, workspace.id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Update context
    # ------------------------------------------------------------------

    async def update_context(
        self,
        db: aiosqlite.Connection,
        workspace_id: str,
        agent_type: str,
        structured_output: dict[str, Any],
        *,
        summary: str | None = None,
    ) -> int:
        """Write agent output to context, log the run, bump version.

        Args:
            db: Database connection.
            workspace_id: The workspace to update.
            agent_type: One of the AgentType literals (e.g. "finding_enricher").
            structured_output: The agent's structured output dict.
            summary: Optional one-line summary for the agent run log.

        Returns:
            The new context_version number.

        Raises:
            ValueError: If agent_type is not recognized.
            FileNotFoundError: If workspace directory doesn't exist.
        """
        if agent_type not in AGENT_TYPE_TO_SECTION:
            raise ValueError(
                f"Unknown agent_type: {agent_type!r}. "
                f"Must be one of {list(AGENT_TYPE_TO_SECTION.keys())}"
            )

        section = AGENT_TYPE_TO_SECTION[agent_type]

        # 1. Write context section (auto-regenerates CONTEXT.md)
        self._dir_manager.write_context_section(workspace_id, section, structured_output)

        ws_dir = self._dir_manager.get(workspace_id)
        if ws_dir is None:
            raise FileNotFoundError(f"Workspace directory not found: {workspace_id}")

        # 2. Log to agent-runs.jsonl
        run_log = AgentRunLog(ws_dir.agent_runs_log)
        run_log.append(agent_type=agent_type, status="completed", summary=summary)

        # 3. Bump version in DB
        new_version = await increment_context_version(db, workspace_id)

        logger.info(
            "Updated context for workspace %s: %s -> v%d",
            workspace_id, agent_type, new_version,
        )
        return new_version

    # ------------------------------------------------------------------
    # Plan approval (PRD-0006 Story 3)
    # ------------------------------------------------------------------

    async def mark_plan_approved(
        self, db: aiosqlite.Connection, workspace_id: str
    ) -> dict[str, Any] | None:
        """Flip ``plan.approved=True`` in BOTH stores: SQLite sidebar (read by
        the Issues-page derivation) AND filesystem ``context/plan.json``
        (read by the pipeline's ``suggest_next`` to decide whether the
        executor may run).

        Returns the updated plan dict, or ``None`` if no plan exists yet.
        """
        sidebar = await _repo_mark_plan_approved(db, workspace_id)
        if sidebar is None or not sidebar.plan:
            return None

        # Mirror the flag into the filesystem context so suggest_next sees it.
        existing = self._dir_manager.read_context_section(workspace_id, "plan") or {}
        if not existing.get("approved"):
            self._dir_manager.write_context_section(
                workspace_id, "plan", {**existing, "approved": True}
            )

        return sidebar.plan

    # ------------------------------------------------------------------
    # Read context
    # ------------------------------------------------------------------

    async def get_context_snapshot(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Return full context state for the sidebar/API.

        Returns dict with keys: finding, enrichment, ownership, exposure,
        plan, validation, agent_run_history. Values are dicts or None.

        Raises:
            FileNotFoundError: If workspace directory doesn't exist.
        """
        ws_dir = self._dir_manager.get(workspace_id)
        if ws_dir is None:
            raise FileNotFoundError(f"Workspace directory not found: {workspace_id}")

        finding_data = json.loads(ws_dir.finding_json.read_text())
        all_context = self._dir_manager.read_all_context(workspace_id)
        run_log = AgentRunLog(ws_dir.agent_runs_log)

        return {
            "finding": finding_data,
            **all_context,
            "agent_run_history": run_log.read_all(),
        }

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_workspace(
        self,
        db: aiosqlite.Connection,
        workspace_id: str,
    ) -> bool:
        """Delete workspace directory and DB row.

        Tolerates missing directory — always attempts DB deletion.
        Returns True if the DB row existed.
        """
        self._dir_manager.delete(workspace_id)
        return await delete_workspace(db, workspace_id)

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    async def archive_workspace(
        self,
        db: aiosqlite.Connection,
        workspace_id: str,
    ) -> Path:
        """Archive workspace directory and update DB state to 'closed'.

        Returns the path to the created archive.

        Raises:
            FileNotFoundError: If workspace directory doesn't exist.
        """
        archive_path = self._dir_manager.archive(workspace_id)
        await update_workspace(
            db, workspace_id, WorkspaceUpdate(state="closed")
        )
        logger.info("Archived workspace %s to %s", workspace_id, archive_path)
        return archive_path
