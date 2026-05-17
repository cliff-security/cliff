"""Code-integrity posture checks (Epic 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from opensec.assessment.posture import RepoCoords
from opensec.assessment.posture.code_integrity import (
    check_code_owners_exists,
    check_secret_scanning_enabled,
)
from opensec.assessment.posture.github_client import UnableToVerify

if TYPE_CHECKING:
    from pathlib import Path


def test_code_owners_exists_at_root(tmp_path: Path) -> None:
    (tmp_path / "CODEOWNERS").write_text("*  @galanko\n")
    result = check_code_owners_exists(tmp_path)
    assert result.status == "pass"
    assert result.detail == {"path": "CODEOWNERS"}


def test_code_owners_exists_in_dot_github(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("*  @galanko\n")
    result = check_code_owners_exists(tmp_path)
    assert result.status == "pass"
    assert result.detail == {"path": ".github/CODEOWNERS"}


def test_code_owners_exists_in_docs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CODEOWNERS").write_text("*  @galanko\n")
    result = check_code_owners_exists(tmp_path)
    assert result.status == "pass"
    assert result.detail == {"path": "docs/CODEOWNERS"}


def test_code_owners_missing_fails(tmp_path: Path) -> None:
    result = check_code_owners_exists(tmp_path)
    assert result.status == "fail"
    assert result.detail["searched"] == [
        "CODEOWNERS",
        ".github/CODEOWNERS",
        "docs/CODEOWNERS",
    ]


class _StubClient:
    def __init__(self, info: Any) -> None:
        self._info = info

    async def get_repo_info(self, owner: str, repo: str) -> Any:
        return self._info


@pytest.mark.asyncio
async def test_secret_scanning_enabled_pass() -> None:
    client = _StubClient(
        {"security_and_analysis": {"secret_scanning": {"status": "enabled"}}}
    )
    result = await check_secret_scanning_enabled(
        client, RepoCoords(owner="o", repo="r", branch="main")
    )
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_secret_scanning_disabled_fail() -> None:
    client = _StubClient(
        {"security_and_analysis": {"secret_scanning": {"status": "disabled"}}}
    )
    result = await check_secret_scanning_enabled(
        client, RepoCoords(owner="o", repo="r", branch="main")
    )
    assert result.status == "fail"


@pytest.mark.asyncio
async def test_secret_scanning_unknown_when_pat_lacks_scope() -> None:
    client = _StubClient(UnableToVerify(reason="http_403"))
    result = await check_secret_scanning_enabled(
        client, RepoCoords(owner="o", repo="r", branch="main")
    )
    assert result.status == "unknown"
    assert result.detail == {"reason": "http_403"}
