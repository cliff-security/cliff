"""Regex-based secret scanner.

High-specificity patterns only — the PRD accepts this is a best-effort check
("no obvious secrets detected"). `.cliff/secrets-ignore` (one relative
path per line) allow-lists known false-positive files like samples.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from cliff.assessment._fs import iter_repo_files
from cliff.assessment.posture import PostureCheckResult

if TYPE_CHECKING:
    from pathlib import Path

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_akia", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_ghp", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_ghs", re.compile(r"ghs_[A-Za-z0-9]{36}")),
    ("stripe_sk_live", re.compile(r"sk_live_[A-Za-z0-9]{24,}")),
    ("google_aiza", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("pem_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

_MAX_FILE_BYTES = 1_048_576


def scan_for_secrets(repo_path: Path) -> PostureCheckResult:
    ignore_paths = _load_ignore_list(repo_path)
    matches: list[dict[str, Any]] = []

    for file_path in iter_repo_files(repo_path):
        rel = file_path.relative_to(repo_path).as_posix()
        if rel in ignore_paths:
            continue
        try:
            if file_path.stat().st_size > _MAX_FILE_BYTES:
                continue
            content = file_path.read_text(errors="ignore")
        except OSError:
            continue
        for rule_name, pattern in _PATTERNS:
            if pattern.search(content):
                matches.append({"rule": rule_name, "file": rel})

    if matches:
        return PostureCheckResult(
            check_name="no_secrets_in_code",
            status="fail",
            detail={"matches": matches},
        )
    return PostureCheckResult(
        check_name="no_secrets_in_code",
        status="pass",
        detail={"matches": []},
    )


def _load_ignore_list(repo_path: Path) -> set[str]:
    ignore_file = repo_path / ".cliff" / "secrets-ignore"
    if not ignore_file.is_file():
        return set()
    return {
        line.strip()
        for line in ignore_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
