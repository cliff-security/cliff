"""RepoDirManager — the per-repo Project-profile store on disk (ADR-0053 §2).

Mirrors ``WorkspaceDirManager`` (the per-*finding* runtime) for the per-*repo*
tier, with two deliberate differences the shared store needs:

* **Atomic writes** (tmp + ``os.replace``). The workspace runtime relies on a
  one-writer-per-directory invariant; the repo store is read by many concurrent
  triage runs while the profiler writes, so a reader must never see a
  half-written file — it gets the previous committed version instead.
* **Lazy ``PROFILE.md``.** The human/agent digest is regenerated on
  profile-complete via :meth:`regenerate_profile_md`, **not** on every artifact
  write (``code_map.json`` for a monorepo can be large, unlike the tiny
  workspace sections).

Source of truth is the JSON artifacts; ``PROFILE.md`` is generated from them.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: Bump when an artifact's on-disk shape changes incompatibly. A mismatch means
#: "stale — rebuild," never "migrate" (ADR-0053 §5): the artifacts are
#: regenerable derivatives.
SCHEMA_VERSION = 1

#: The Project-profile artifacts (ADR-0053 §3). The clone lives alongside in
#: ``repo/`` (see :meth:`clone_dir`).
ARTIFACTS = ("profile", "code_map", "threat")


class RepoDirManager:
    """Creates and serves per-repo store directories under ``base_dir``."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # -- paths --------------------------------------------------------------

    def _repo_root(self, repo_id: str) -> Path:
        _validate_repo_id(repo_id)
        return self._base_dir / repo_id

    def repo_dir(self, repo_id: str) -> str:
        """The store directory path, as a string for ``repo.profile_dir``."""
        return str(self._repo_root(repo_id))

    def clone_dir(self, repo_id: str) -> Path:
        """The one cached clone for this repo (ADR-0052 §3 reads it read-only)."""
        return self._repo_root(repo_id) / "repo"

    def profile_md_path(self, repo_id: str) -> Path:
        return self._repo_root(repo_id) / "PROFILE.md"

    def ensure(self, repo_id: str) -> Path:
        root = self._repo_root(repo_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    # -- artifacts ----------------------------------------------------------

    def write_artifact(self, repo_id: str, name: str, data: dict) -> None:
        if name not in ARTIFACTS:
            raise ValueError(
                f"Unknown profile artifact {name!r}; expected one of {ARTIFACTS}"
            )
        root = self.ensure(repo_id)
        _atomic_write_json(root / f"{name}.json", data)

    def read_artifact(self, repo_id: str, name: str) -> dict | None:
        path = self._repo_root(repo_id) / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    # -- manifest -----------------------------------------------------------

    def write_manifest(
        self,
        repo_id: str,
        *,
        source_sha: str | None = None,
        built_at: str | None = None,
    ) -> dict:
        """Write the index of what the store holds and how fresh it is."""
        root = self.ensure(repo_id)
        present = [n for n in ARTIFACTS if (root / f"{n}.json").exists()]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "source_sha": source_sha,
            "built_at": built_at,
            "artifacts": present,
        }
        _atomic_write_json(root / "MANIFEST.json", manifest)
        return manifest

    def read_manifest(self, repo_id: str) -> dict | None:
        path = self._repo_root(repo_id) / "MANIFEST.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    # -- generated digest ---------------------------------------------------

    def regenerate_profile_md(self, repo_id: str) -> None:
        """Rebuild ``PROFILE.md`` from the current artifacts (call on complete)."""
        root = self.ensure(repo_id)
        sections = {name: self.read_artifact(repo_id, name) for name in ARTIFACTS}
        _atomic_write_text(root / "PROFILE.md", _render_profile_md(sections))

    # -- delete -------------------------------------------------------------

    def delete(self, repo_id: str) -> bool:
        root = self._repo_root(repo_id)
        if not root.exists():
            return False
        shutil.rmtree(root)
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* atomically — a concurrent reader sees old-or-new, never torn."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data: dict) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")


def _render_profile_md(sections: dict[str, dict | None]) -> str:
    """Render a readable digest from the artifacts (the source of truth).

    Deliberately generic: it renders the scalar top-level fields of whatever
    artifacts are present. The profile builders (later) define the exact shapes;
    this stays robust to that without coupling to a schema that doesn't exist
    yet.
    """
    lines = ["# Project profile", ""]
    present = {name: data for name, data in sections.items() if data}
    if not present:
        lines.append("_No profile built yet._")
        return "\n".join(lines) + "\n"
    for name, data in present.items():
        lines.append(f"## {name.replace('_', ' ')}")
        lines.append("")
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)):
                lines.append(f"- **{key}:** {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _validate_repo_id(repo_id: str) -> None:
    if not repo_id:
        raise ValueError("repo_id must not be empty")
    if "/" in repo_id or "\\" in repo_id:
        raise ValueError(f"repo_id must not contain path separators: {repo_id!r}")
    if repo_id in (".", ".."):
        raise ValueError(f"repo_id must not be a relative path component: {repo_id!r}")
