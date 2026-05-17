"""Repo clone helper (Epic 1) — extracted subprocess + token scrubbing pattern."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from cliff.assessment.clone import (
    CloneError,
    CloneTimeoutError,
    inject_token,
    redact_token,
    shallow_clone,
    validate_repo_url,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_validate_repo_url_accepts_https_github() -> None:
    validate_repo_url("https://github.com/example/repo.git", has_token=True)


def test_validate_repo_url_rejects_http() -> None:
    with pytest.raises(ValueError, match="https"):
        validate_repo_url("http://github.com/x/y", has_token=False)


def test_validate_repo_url_rejects_token_for_non_github_host() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        validate_repo_url("https://gitlab.com/x/y", has_token=True)


def test_inject_token_rewrites_netloc() -> None:
    rewritten = inject_token("https://github.com/x/y", "ghp_secret")
    assert rewritten == "https://x-access-token:ghp_secret@github.com/x/y"


def test_inject_token_no_op_without_token() -> None:
    assert inject_token("https://github.com/x/y", None) == "https://github.com/x/y"


def test_redact_token_scrubs_url_pattern_and_raw_token() -> None:
    text = "fatal: clone https://x-access-token:ghp_xxx@github.com/x/y failed (ghp_xxx)"
    scrubbed = redact_token(text, "ghp_xxx")
    assert "ghp_xxx" not in scrubbed
    assert "x-access-token:***@" in scrubbed


@pytest.mark.asyncio
async def test_shallow_clone_success(tmp_path: Path) -> None:
    """shallow_clone delegates to git via asyncio.create_subprocess_exec."""

    # Build a fake successful subprocess.
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    proc.pid = 12345

    async def fake_exec(*args: object, **kwargs: object) -> object:
        return proc

    target = tmp_path / "out"
    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await shallow_clone(
            "https://github.com/x/y", target=target, token=None, timeout_s=30
        )


@pytest.mark.asyncio
async def test_shallow_clone_auth_injects_token(tmp_path: Path) -> None:
    captured: dict[str, tuple[object, ...]] = {}
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    proc.pid = 1

    async def fake_exec(*args: object, **kwargs: object) -> object:
        captured["args"] = args
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await shallow_clone(
            "https://github.com/x/y",
            target=tmp_path / "out",
            token="ghp_secret",
            timeout_s=30,
        )

    args = captured["args"]
    # Token must appear in the URL we hand to git, but never in plain logs.
    assert any(
        isinstance(a, str) and "x-access-token:ghp_secret" in a for a in args
    ), args


@pytest.mark.asyncio
async def test_shallow_clone_failure_scrubs_token_in_error(tmp_path: Path) -> None:
    proc = AsyncMock()
    proc.communicate.return_value = (
        b"",
        b"fatal: clone https://x-access-token:ghp_secret@github.com/x/y failed (ghp_secret)",
    )
    proc.returncode = 128
    proc.pid = 1

    async def fake_exec(*args: object, **kwargs: object) -> object:
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        pytest.raises(CloneError) as exc,
    ):
        await shallow_clone(
            "https://github.com/x/y",
            target=tmp_path / "out",
            token="ghp_secret",
            timeout_s=30,
        )
    assert "ghp_secret" not in str(exc.value)
    assert "x-access-token:***@" in str(exc.value)


@pytest.mark.asyncio
async def test_shallow_clone_timeout_kills_process_group(tmp_path: Path) -> None:
    proc = AsyncMock()

    async def hang(*_args: object, **_kw: object) -> tuple[bytes, bytes]:
        await asyncio.sleep(60)
        return (b"", b"")

    proc.communicate.side_effect = hang
    proc.returncode = None
    proc.pid = 1
    proc.kill = AsyncMock()
    proc.wait = AsyncMock(return_value=None)

    async def fake_exec(*args: object, **kwargs: object) -> object:
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        patch("os.killpg") as killpg,
        pytest.raises(CloneTimeoutError),
    ):
        await shallow_clone(
                "https://github.com/x/y",
                target=tmp_path / "out",
                token=None,
                timeout_s=0.1,
            )
    # We expect the process group to be killed for any non-zero pid.
    killpg.assert_called()
