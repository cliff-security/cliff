"""Per-assessment scope detection (IMPL-0009).

Walks a freshly-cloned repo to compute the values the new dashboard
"Last assessment" panel surfaces:

* ``commit_sha`` — current HEAD (best-effort via ``git rev-parse``).
* ``scanned_files`` — count of regular files outside skip-dirs.
* ``scanned_deps`` — sum of resolved entries across detected lockfiles.
* ``ecosystems`` — sorted CSV of detected package-manager ecosystems.

Every helper is best-effort: a missing or unparseable lockfile is silently
skipped so engine instrumentation never fails an assessment over UI text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from cliff.assessment._fs import SKIP_DIRS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


_ECOSYSTEM_MANIFESTS: dict[str, tuple[str, ...]] = {
    "npm": ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
    "pip": (
        "requirements.txt",
        "Pipfile",
        "Pipfile.lock",
        "pyproject.toml",
        "poetry.lock",
        "uv.lock",
        "setup.py",
    ),
    "rubygems": ("Gemfile", "Gemfile.lock"),
    "go": ("go.mod", "go.sum"),
    "cargo": ("Cargo.toml", "Cargo.lock"),
    "maven": ("pom.xml",),
    "gradle": ("build.gradle", "build.gradle.kts"),
}


async def capture_commit_sha(repo_path: Path) -> str | None:
    """Return the short SHA of HEAD or ``None`` if rev-parse fails.

    Used to populate ``Assessment.commit_sha``. Failure is silent — we never
    block an assessment on git plumbing.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo_path),
            "rev-parse",
            "--short",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    sha = stdout_b.decode("utf-8", errors="replace").strip()
    return sha or None


def count_scanned_files(repo_path: Path) -> int:
    """Count regular files in the repo, skipping ``.git`` and SKIP_DIRS.

    Mirrors the boundary Trivy and Semgrep walk after applying their
    exclude flags, so the dashboard number lines up with the scanners.
    """
    skip = set(SKIP_DIRS) | {".git"}
    total = 0
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.relative_to(repo_path).parts):
            continue
        total += 1
    return total


def detect_ecosystems(repo_path: Path) -> list[str]:
    """Return sorted ecosystem names whose manifests exist in the repo."""
    found: set[str] = set()
    for name, manifests in _ECOSYSTEM_MANIFESTS.items():
        for m in manifests:
            if (repo_path / m).is_file():
                found.add(name)
                break
    return sorted(found)


def count_dependencies(repo_path: Path) -> int:
    """Sum resolved-dependency counts across detected lockfiles.

    Best-effort. Each parser swallows its own errors; an unrecognised
    or malformed file contributes 0 rather than aborting the count.
    """
    total = 0
    total += _count_npm(repo_path)
    total += _count_pip(repo_path)
    total += _count_rubygems(repo_path)
    total += _count_go(repo_path)
    total += _count_cargo(repo_path)
    total += _count_pyproject_lock(repo_path)
    return total


# ─── per-ecosystem parsers ─────────────────────────────────────────────────


def _count_npm(repo_path: Path) -> int:
    lock = repo_path / "package-lock.json"
    if not lock.is_file():
        return 0
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    packages = data.get("packages")
    if isinstance(packages, dict):
        # npm v3+: keys are "" (root), "node_modules/foo", etc.
        return sum(1 for k in packages if k and k != "")
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        return _walk_npm_v1_deps(deps)
    return 0


def _walk_npm_v1_deps(node: dict) -> int:
    total = len(node)
    for v in node.values():
        if isinstance(v, dict) and isinstance(v.get("dependencies"), dict):
            total += _walk_npm_v1_deps(v["dependencies"])
    return total


_PIP_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _count_pip(repo_path: Path) -> int:
    total = 0
    req = repo_path / "requirements.txt"
    if req.is_file():
        try:
            for line in req.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                    continue
                if _PIP_REQ_LINE.match(stripped):
                    total += 1
        except OSError:
            pass

    pipfile_lock = repo_path / "Pipfile.lock"
    if pipfile_lock.is_file():
        try:
            data = json.loads(pipfile_lock.read_text(encoding="utf-8"))
            for key in ("default", "develop"):
                section = data.get(key)
                if isinstance(section, dict):
                    total += len(section)
        except (OSError, json.JSONDecodeError):
            pass

    poetry_lock = repo_path / "poetry.lock"
    if poetry_lock.is_file():
        try:
            text = poetry_lock.read_text(encoding="utf-8")
            total += text.count("[[package]]")
        except OSError:
            pass

    uv_lock = repo_path / "uv.lock"
    if uv_lock.is_file():
        try:
            text = uv_lock.read_text(encoding="utf-8")
            total += text.count("[[package]]")
        except OSError:
            pass

    return total


_GEMFILE_LOCK_DEP = re.compile(r"^    [a-z0-9_\-]+ \(", re.MULTILINE)


def _count_rubygems(repo_path: Path) -> int:
    lock = repo_path / "Gemfile.lock"
    if not lock.is_file():
        return 0
    try:
        text = lock.read_text(encoding="utf-8")
    except OSError:
        return 0
    return len(_GEMFILE_LOCK_DEP.findall(text))


def _count_go(repo_path: Path) -> int:
    sumfile = repo_path / "go.sum"
    if not sumfile.is_file():
        return 0
    try:
        # Each module appears twice in go.sum (once with /go.mod suffix).
        # Count unique module-paths to avoid double-counting.
        lines = sumfile.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    modules: set[str] = set()
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            modules.add(parts[0])
    return len(modules)


def _count_cargo(repo_path: Path) -> int:
    lock = repo_path / "Cargo.lock"
    if not lock.is_file():
        return 0
    try:
        text = lock.read_text(encoding="utf-8")
    except OSError:
        return 0
    return text.count("[[package]]")


def _count_pyproject_lock(repo_path: Path) -> int:
    """Currently absorbed by ``_count_pip`` (poetry.lock / uv.lock). Reserved
    for future Python lockfile formats so the public surface stays stable."""
    return 0


__all__ = [
    "capture_commit_sha",
    "count_dependencies",
    "count_scanned_files",
    "detect_ecosystems",
]
