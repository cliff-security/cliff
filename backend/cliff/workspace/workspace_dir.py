"""WorkspaceDir value object — typed access to workspace directory paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Maps AgentType literals to context file section names.
AGENT_TYPE_TO_SECTION: dict[str, str] = {
    "finding_enricher": "enrichment",
    "owner_resolver": "ownership",
    "exposure_analyzer": "exposure",
    "evidence_collector": "evidence",
    "remediation_planner": "plan",
    "remediation_executor": "remediation",
    "validation_checker": "validation",
}

# All known context sections (order matters — this is the agent pipeline order).
# validation_checker is on-demand only — it verifies a fix that does not exist
# until the executor runs, so it is not part of the forward pipeline walk.
CONTEXT_SECTIONS: list[str] = [
    "enrichment",
    "ownership",
    "exposure",
    "evidence",
    "plan",
    "remediation",
    "validation",
]


@dataclass(frozen=True)
class WorkspaceDir:
    """Immutable reference to a workspace directory and its known file locations.

    Pure value object — no I/O. All properties return Path objects that may
    or may not exist on disk.
    """

    root: Path

    @property
    def workspace_id(self) -> str:
        return self.root.name

    # --- Top-level files ---

    @property
    def context_md(self) -> Path:
        return self.root / "CONTEXT.md"

    # --- context/ ---

    @property
    def context_dir(self) -> Path:
        return self.root / "context"

    @property
    def finding_json(self) -> Path:
        return self.root / "context" / "finding.json"

    @property
    def finding_md(self) -> Path:
        return self.root / "context" / "finding.md"

    @property
    def code_snippets_dir(self) -> Path:
        return self.root / "context" / "code-snippets"

    @property
    def references_dir(self) -> Path:
        return self.root / "context" / "references"

    def context_file(self, section: str) -> Path:
        """Return path for a context section file (enrichment, ownership, etc)."""
        return self.root / "context" / f"{section}.json"

    # --- history/ ---

    @property
    def history_dir(self) -> Path:
        return self.root / "history"

    @property
    def agent_runs_log(self) -> Path:
        return self.root / "history" / "agent-runs.jsonl"

    def exists(self) -> bool:
        return self.root.is_dir()
