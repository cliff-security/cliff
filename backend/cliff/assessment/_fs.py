"""Shared filesystem helpers for the assessment module."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

SKIP_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        # Test data directories — lockfiles under these paths are intentional
        # inputs to the assessment engine's own unit tests (or the user's), not
        # real runtime dependencies. Without this exclusion we report hundreds
        # of false-positive CVEs on any repo whose parser tests ship an
        # intentionally-vulnerable lockfile (including Cliff itself).
        "fixtures",
        "testdata",
        "test-fixtures",
        "test_fixtures",
    }
)

# Size cap for untrusted lockfiles — a pathological monorepo can produce
# lockfiles large enough to OOM a worker. Anything above is skipped.
MAX_LOCKFILE_BYTES = 16 * 1_048_576


def iter_repo_files(root: Path) -> Iterable[Path]:
    """Yield every regular file under `root`, skipping vendored/build dirs."""
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


class LockfileTooLargeError(Exception):
    """Raised when a lockfile exceeds `MAX_LOCKFILE_BYTES`."""


def safe_read_text(path: Path, *, max_bytes: int = MAX_LOCKFILE_BYTES) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise LockfileTooLargeError(f"cannot stat {path}: {exc}") from exc
    if size > max_bytes:
        raise LockfileTooLargeError(f"{path} is {size} bytes (> {max_bytes})")
    return path.read_text()
