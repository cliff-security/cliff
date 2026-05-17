"""Checksum verification for pinned scanner binaries (Epic 1 / ADR-0028)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cliff.assessment.scanners.verify import (
    ChecksumMismatchError,
    VerifyMode,
    parse_versions_file,
    verify_scanner_checksums,
)


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_parse_versions_file_handles_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / ".scanner-versions"
    path.write_text(
        "# Cliff pinned scanners (Epic 1)\n"
        "\n"
        "trivy 0.52.0 abcdef1234\n"
        "# semgrep is required\n"
        "semgrep 1.70.0 cafef00d\n"
    )
    parsed = parse_versions_file(path)
    assert parsed == {
        "trivy": ("0.52.0", "abcdef1234"),
        "semgrep": ("1.70.0", "cafef00d"),
    }


def test_verify_strict_passes_when_checksums_match(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    trivy = bin_dir / "trivy"
    semgrep = bin_dir / "semgrep"
    trivy.write_bytes(b"trivy-binary-bytes")
    semgrep.write_bytes(b"semgrep-binary-bytes")

    versions = tmp_path / ".scanner-versions"
    versions.write_text(
        f"trivy 0.52.0 {_sha256(b'trivy-binary-bytes')}\n"
        f"semgrep 1.70.0 {_sha256(b'semgrep-binary-bytes')}\n"
    )
    # Should not raise.
    verify_scanner_checksums(bin_dir=bin_dir, versions_file=versions, mode=VerifyMode.STRICT)


def test_checksum_verify_strict_raises_on_mismatch(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "trivy").write_bytes(b"actual-bytes")
    (bin_dir / "semgrep").write_bytes(b"semgrep-bytes")

    versions = tmp_path / ".scanner-versions"
    versions.write_text(
        f"trivy 0.52.0 deadbeef\n"  # wrong
        f"semgrep 1.70.0 {_sha256(b'semgrep-bytes')}\n"
    )
    with pytest.raises(ChecksumMismatchError) as exc:
        verify_scanner_checksums(
            bin_dir=bin_dir, versions_file=versions, mode=VerifyMode.STRICT
        )
    assert "trivy" in str(exc.value)


def test_checksum_verify_warn_mode_proceeds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "trivy").write_bytes(b"actual-bytes")
    (bin_dir / "semgrep").write_bytes(b"semgrep-bytes")

    versions = tmp_path / ".scanner-versions"
    versions.write_text(
        f"trivy 0.52.0 deadbeef\n"
        f"semgrep 1.70.0 {_sha256(b'semgrep-bytes')}\n"
    )
    # Should not raise — but should log a warning.
    with caplog.at_level("WARNING"):
        verify_scanner_checksums(
            bin_dir=bin_dir, versions_file=versions, mode=VerifyMode.WARN
        )
    assert any("trivy" in rec.message for rec in caplog.records)


def test_verify_strict_raises_when_binary_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    versions = tmp_path / ".scanner-versions"
    versions.write_text("trivy 0.52.0 abc\n")
    with pytest.raises(FileNotFoundError):
        verify_scanner_checksums(
            bin_dir=bin_dir, versions_file=versions, mode=VerifyMode.STRICT
        )
