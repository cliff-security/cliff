"""Subprocess-only scanner runners (ADR-0028).

Trivy and Semgrep are invoked as pinned-checksum binaries in
``<data_dir>/bin/``; everything they receive — args, env, cwd — flows
through :class:`SubprocessScannerRunner`. The runner enforces the env
whitelist (``PATH``, ``HOME``, ``LANG``, ``TRIVY_CACHE_DIR``,
``SEMGREP_RULES_CACHE_DIR``) so credentials like ``GITHUB_PAT`` cannot
leak into a third-party binary's process.
"""

from __future__ import annotations

from cliff.assessment.scanners.models import (
    ScannerInfo,
    ScannerStatus,
    SemgrepFinding,
    SemgrepResult,
    TrivyMisconfiguration,
    TrivyResult,
    TrivySecret,
    TrivyVulnerability,
)
from cliff.assessment.scanners.runner import (
    SCANNER_ENV_ALLOW,
    ScannerRunner,
    ScannerTimeoutError,
    SubprocessScannerRunner,
)
from cliff.assessment.scanners.verify import (
    ChecksumMismatchError,
    VerifyMode,
    parse_versions_file,
    verify_scanner_checksums,
)

__all__ = [
    "SCANNER_ENV_ALLOW",
    "ChecksumMismatchError",
    "ScannerInfo",
    "ScannerRunner",
    "ScannerStatus",
    "ScannerTimeoutError",
    "SemgrepFinding",
    "SemgrepResult",
    "SubprocessScannerRunner",
    "TrivyMisconfiguration",
    "TrivyResult",
    "TrivySecret",
    "TrivyVulnerability",
    "VerifyMode",
    "parse_versions_file",
    "verify_scanner_checksums",
]
