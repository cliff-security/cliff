"""SHA256 verification for pinned scanner binaries (ADR-0028)."""

from __future__ import annotations

import hashlib
import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ChecksumMismatchError(RuntimeError):
    """Raised in strict mode when a binary's SHA256 differs from the pinned value."""


class VerifyMode(StrEnum):
    STRICT = "strict"
    WARN = "warn"


def parse_versions_file(path: Path) -> dict[str, tuple[str, str]]:
    """Parse ``.scanner-versions`` into ``{name: (version, sha256)}``.

    Comments (``#``) and blank lines are ignored. Lines must look like
    ``<name> <version> <sha256>``. Anything else raises ``ValueError``.
    """
    parsed: dict[str, tuple[str, str]] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(
                f"malformed line in {path}: expected 'name version sha256', got: {raw_line!r}"
            )
        name, version, sha = parts
        parsed[name] = (version, sha)
    return parsed


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_scanner_checksums(
    *, bin_dir: Path, versions_file: Path, mode: VerifyMode = VerifyMode.STRICT
) -> None:
    """Verify pinned binaries match their recorded SHA256.

    In :attr:`VerifyMode.STRICT` (default) any mismatch raises
    :class:`ChecksumMismatchError`. In :attr:`VerifyMode.WARN` the runner logs
    a warning but proceeds — used for local development where the binary may
    have been rebuilt by the developer.

    Missing binaries always raise :class:`FileNotFoundError`; warn mode is for
    *integrity*, not *presence*.
    """
    pinned = parse_versions_file(versions_file)
    for name, (_version, expected_sha) in pinned.items():
        bin_path = bin_dir / name
        if not bin_path.exists():
            raise FileNotFoundError(f"pinned scanner binary not found: {bin_path}")
        actual = _hash_file(bin_path)
        if actual == expected_sha:
            continue
        message = (
            f"checksum mismatch for {name}: expected {expected_sha}, got {actual}"
        )
        if mode == VerifyMode.STRICT:
            raise ChecksumMismatchError(message)
        logger.warning(message)
