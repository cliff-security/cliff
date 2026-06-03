"""WorkspaceDirManager — CRUD for workspace directories on disk."""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import tarfile
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from cliff.workspace.context_document import ContextDocument
from cliff.workspace.workspace_dir import CONTEXT_SECTIONS, WorkspaceDir

if TYPE_CHECKING:
    from pathlib import Path

    from cliff.models import Finding

logger = logging.getLogger(__name__)


def _git_ancestor(path: Path) -> Path | None:
    """Return the nearest ancestor of *path* that contains a ``.git`` entry,
    or None if there is none up to the filesystem root.

    Used to detect the dangerous topology where workspace directories are
    nested inside a git repository — see ``__init__`` for why that matters.
    """
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


class WorkspaceKind(StrEnum):
    """Discriminator for workspace directories (IMPL-0002 Milestone E4).

    Finding workspaces (the existing kind) are implicit; the two repo-scoped
    actions get explicit enum values that route to their generator agents.
    """

    repo_action_security_md = "repo_action_security_md"
    repo_action_dependabot = "repo_action_dependabot"


class WorkspaceDirManager:
    """Creates, reads, updates, archives, and deletes workspace directories.

    Each workspace gets an isolated directory with context files, agent
    definitions, and an auto-generated CONTEXT.md. This is the filesystem
    foundation that the AI engine reads from.

    All operations are synchronous — filesystem I/O does not benefit from
    async. Accepts ``base_dir`` as a constructor parameter so tests can
    use ``tmp_path``.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

        # Workspace-isolation guard (post-mortem). Remediation agents run
        # ``git`` themselves (ADR-0024). ``git`` searches parent directories
        # for ``.git`` — so if a workspace's clone is missing/partial and the
        # agent runs ``git checkout``/``reset``, git escapes UP the tree into
        # whatever repository the workspace dir is nested inside. When that's
        # a developer's working tree (or a user's local checkout being
        # secured), a stray ``git reset --hard`` is silent, unrecoverable
        # data loss. The hard block is ``GIT_CEILING_DIRECTORIES`` injected
        # per-process (see ``engine/pool.py``); this is the early-warning:
        # surface the risky topology loudly at startup so it's never a
        # silent surprise.
        git_root = _git_ancestor(base_dir)
        if git_root is not None:
            logger.warning(
                "Workspace root %s is nested inside a git repository (%s). "
                "Agent git operations are confined via GIT_CEILING_DIRECTORIES, "
                "but the safest topology keeps workspace dirs outside any git "
                "tree. This is expected in a dev worktree; flag it if seen in "
                "a packaged/Docker deployment.",
                base_dir,
                git_root,
            )

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        workspace_id: str,
        finding: Finding,
    ) -> WorkspaceDir:
        """Create the full directory structure and initial files for a workspace.

        Args:
            workspace_id: Unique workspace identifier.
            finding: The finding this workspace remediates.

        Raises:
            FileExistsError: If the workspace directory already exists.
            ValueError: If workspace_id contains path traversal characters.
        """
        _validate_workspace_id(workspace_id)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        workspace_root = self._base_dir / workspace_id
        if workspace_root.exists():
            raise FileExistsError(
                f"Workspace directory already exists: {workspace_root}"
            )

        # Create directory tree
        workspace_root.mkdir()
        (workspace_root / "context").mkdir()
        (workspace_root / "context" / "code-snippets").mkdir()
        (workspace_root / "context" / "references").mkdir()
        (workspace_root / "history").mkdir()

        ws = WorkspaceDir(root=workspace_root)

        # Write finding data
        finding_data = finding.model_dump(mode="json")
        ws.finding_json.write_text(json.dumps(finding_data, indent=2) + "\n")
        ws.finding_md.write_text(_render_finding_md(finding))

        # Create empty agent-runs log
        ws.agent_runs_log.touch()

        # Generate CONTEXT.md
        context_md_content = ContextDocument.generate(finding_data)
        ws.context_md.write_text(context_md_content)

        return ws

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, workspace_id: str) -> WorkspaceDir | None:
        """Return WorkspaceDir if the directory exists, else None."""
        ws = WorkspaceDir(root=self._base_dir / workspace_id)
        return ws if ws.exists() else None

    def list(self) -> list[WorkspaceDir]:
        """Return all workspace directories sorted by name."""
        if not self._base_dir.exists():
            return []
        return sorted(
            (
                WorkspaceDir(root=p)
                for p in self._base_dir.iterdir()
                if p.is_dir() and p.name != "archives"
            ),
            key=lambda ws: ws.workspace_id,
        )

    def read_context_section(
        self, workspace_id: str, section: str
    ) -> dict | None:
        """Read a context section JSON file. Returns None if file doesn't exist."""
        ws = self._require_workspace(workspace_id)
        path = ws.context_file(section)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def read_all_context(self, workspace_id: str) -> dict[str, dict | None]:
        """Read all context sections. Returns dict mapping section name to data."""
        return {
            section: self.read_context_section(workspace_id, section)
            for section in CONTEXT_SECTIONS
        }

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def write_context_section(
        self, workspace_id: str, section: str, data: dict
    ) -> None:
        """Write a context section JSON file and regenerate CONTEXT.md.

        Raises:
            FileNotFoundError: If the workspace directory doesn't exist.
        """
        ws = self._require_workspace(workspace_id)
        path = ws.context_file(section)
        path.write_text(json.dumps(data, indent=2) + "\n")
        self.regenerate_context_md(workspace_id)

    def regenerate_context_md(self, workspace_id: str) -> None:
        """Rebuild CONTEXT.md from current context files."""
        ws = self._require_workspace(workspace_id)
        finding_data = json.loads(ws.finding_json.read_text())

        sections = {}
        for section in CONTEXT_SECTIONS:
            path = ws.context_file(section)
            if path.exists():
                sections[section] = json.loads(path.read_text())

        content = ContextDocument.generate(finding_data, **sections)
        ws.context_md.write_text(content)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, workspace_id: str) -> bool:
        """Delete workspace directory recursively. Returns True if it existed."""
        ws = WorkspaceDir(root=self._base_dir / workspace_id)
        if not ws.exists():
            return False
        shutil.rmtree(ws.root)
        return True

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive(self, workspace_id: str) -> Path:
        """Create a tar.gz archive of the workspace directory.

        The archive is written to ``base_dir/archives/<workspace_id>.tar.gz``.
        The original directory is NOT deleted — the caller decides.

        Raises:
            FileNotFoundError: If the workspace directory doesn't exist.
        """
        ws = self._require_workspace(workspace_id)
        archives_dir = self._base_dir / "archives"
        archives_dir.mkdir(exist_ok=True)

        archive_path = archives_dir / f"{workspace_id}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(ws.root, arcname=workspace_id)
        return archive_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_workspace(self, workspace_id: str) -> WorkspaceDir:
        ws = self.get(workspace_id)
        if ws is None:
            raise FileNotFoundError(
                f"Workspace directory not found: {self._base_dir / workspace_id}"
            )
        return ws

    # ------------------------------------------------------------------
    # Repo-scoped workspaces (IMPL-0002 Milestone E — V1↔V2 interface stub)
    # ------------------------------------------------------------------

    def create_repo_workspace(
        self,
        kind: WorkspaceKind,
        repo_url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Create an ephemeral repo-scoped workspace for a generator agent.

        Unlike ``create()``, this does **not** produce finding-scoped files
        (no ``finding.json``, no ``finding.md``, no ``CONTEXT.md``). The
        directory is the clone/edit working tree the Pydantic AI
        repo-action agent (ADR-0024 / ADR-0047) runs in:

        - ``REPO_ACTION.md`` — human-readable summary of the action.
        - ``history/`` — for agent-run logs written later.

        The agent's system prompt + permission policy live in
        ``cliff.agents.runtime.repo_actions``; nothing is rendered to disk.

        Returns:
            The generated workspace_id (a safe single-path-component string).
        """
        self._base_dir.mkdir(parents=True, exist_ok=True)
        workspace_id, workspace_root = self._allocate_workspace_dir(kind)
        (workspace_root / "history").mkdir()

        # Empty agent-runs log mirrors finding workspaces so downstream tooling
        # (tail readers, log rotation) can treat all workspaces uniformly.
        (workspace_root / "history" / "agent-runs.jsonl").touch()

        summary_lines = [
            "# Repo action workspace",
            "",
            f"- **Action:** `{kind.value}`",
            f"- **Repo:** {_scrub_repo_url(repo_url)}",
        ]
        if params:
            summary_lines.append("- **Params:**")
            for key, value in sorted(params.items()):
                summary_lines.append(f"  - `{key}`: `{value}`")
        summary_lines.append("")
        (workspace_root / "REPO_ACTION.md").write_text("\n".join(summary_lines))

        return workspace_id

    def _allocate_workspace_dir(
        self, kind: WorkspaceKind, *, attempts: int = 3
    ) -> tuple[str, Path]:
        """Generate a fresh workspace_id + atomically reserve its directory.

        ``secrets.token_hex(8)`` gives 64 bits of entropy; a second allocation
        colliding with an existing dir is vanishingly unlikely, but we retry
        a handful of times to keep callers from needing collision handling.
        """
        for _ in range(attempts):
            workspace_id = f"repo-{kind.value}-{secrets.token_hex(8)}"
            _validate_workspace_id(workspace_id)
            workspace_root = self._base_dir / workspace_id
            try:
                workspace_root.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return workspace_id, workspace_root
        raise RuntimeError(
            f"Failed to allocate a unique workspace directory after {attempts} attempts"
        )


_CREDENTIALED_URL = re.compile(r"^(https?://)[^/@\s]+@", re.IGNORECASE)


def _scrub_repo_url(url: str) -> str:
    """Strip embedded credentials (``user:token@host``) before persisting the URL.

    Callers sometimes pass URLs like ``https://x-access-token:ghp_xxx@github.com/...``.
    We don't want that ending up in ``REPO_ACTION.md``, which is a plain text
    artefact under ``data/workspaces/`` and may be archived or mirrored.
    """
    return _CREDENTIALED_URL.sub(r"\1", url)


def _validate_workspace_id(workspace_id: str) -> None:
    """Reject workspace IDs that could cause path traversal."""
    if not workspace_id:
        raise ValueError("Workspace ID must not be empty")
    if "/" in workspace_id or "\\" in workspace_id:
        raise ValueError(
            f"Workspace ID must not contain path separators: {workspace_id!r}"
        )
    if workspace_id in (".", ".."):
        raise ValueError(
            f"Workspace ID must not be a relative path component: {workspace_id!r}"
        )


def _render_finding_md(finding: Finding) -> str:
    """Render a human-readable markdown summary of a finding."""
    lines = [f"# {finding.title}", ""]

    lines.append(f"- **Source:** {finding.source_type} / {finding.source_id}")
    lines.append(f"- **Status:** {finding.status}")

    if finding.raw_severity:
        lines.append(f"- **Severity:** {finding.raw_severity}")
    if finding.normalized_priority:
        lines.append(f"- **Priority:** {finding.normalized_priority}")
    if finding.asset_label or finding.asset_id:
        asset = finding.asset_label or finding.asset_id
        lines.append(f"- **Asset:** {asset}")
    if finding.likely_owner:
        lines.append(f"- **Likely owner:** {finding.likely_owner}")

    lines.append("")

    if finding.description:
        lines.append("## Description")
        lines.append("")
        lines.append(finding.description)
        lines.append("")

    if finding.why_this_matters:
        lines.append("## Why this matters")
        lines.append("")
        lines.append(finding.why_this_matters)
        lines.append("")

    return "\n".join(lines)
