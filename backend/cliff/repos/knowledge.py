"""RepoKnowledge — the declared-consumption access layer (ADR-0053 §5).

Agents never open profile files directly. Each Tier-2 agent (ADR-0052)
*declares* which profile sections it consumes; the runtime loads **only** those
into a ``RepoKnowledge`` view and renders them into the prompt — so no agent
pays tokens for a section it doesn't use (the mechanism that makes eager
profiling affordable). Reading actual source is a separate concern: the
read/grep tools over :attr:`RepoKnowledge.clone_dir`.

This mirrors how ``WorkspaceDeps`` already feeds per-finding context to agents,
for the per-repo tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cliff.repos.repo_dir_manager import ARTIFACTS

if TYPE_CHECKING:
    from pathlib import Path

    from cliff.repos.repo_dir_manager import RepoDirManager


@dataclass(frozen=True)
class RepoKnowledge:
    """A read-only, section-scoped view of one repo's Project profile.

    A section is ``None`` when the agent didn't declare it OR when it hasn't
    been built yet — agents must treat ``None`` as "not available" and degrade,
    never assume.
    """

    repo_id: str
    profile: dict | None = None
    code_map: dict | None = None
    threat: dict | None = None
    clone_dir: Path | None = None


def load_repo_knowledge(
    mgr: RepoDirManager,
    repo_id: str,
    sections: list[str],
    *,
    include_clone: bool = False,
) -> RepoKnowledge:
    """Load *only* the declared profile *sections* for *repo_id*.

    Args:
        sections: which artifacts the consuming agent declared (subset of
            ``ARTIFACTS``). Anything outside that set is a programming error.
        include_clone: when True, expose the cached clone path for the
            read/grep tools (``Trace the path``); otherwise left ``None``.
    """
    selected = set(sections)
    unknown = selected - set(ARTIFACTS)
    if unknown:
        raise ValueError(
            f"Unknown profile section(s) {sorted(unknown)}; expected subset of {ARTIFACTS}"
        )
    return RepoKnowledge(
        repo_id=repo_id,
        profile=mgr.read_artifact(repo_id, "profile") if "profile" in selected else None,
        code_map=mgr.read_artifact(repo_id, "code_map") if "code_map" in selected else None,
        threat=mgr.read_artifact(repo_id, "threat") if "threat" in selected else None,
        clone_dir=mgr.clone_dir(repo_id) if include_clone else None,
    )
