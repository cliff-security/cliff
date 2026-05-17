"""Per-workspace npm cache isolation (EF-B15).

Two workspaces spawned through ``WorkspaceProcessPool`` must each see a
``NPM_CONFIG_CACHE`` that points inside their own dir — not a shared
``~/.npm`` and not each other's. Without this isolation, concurrent
``npm install`` invocations under load amplify into a retry storm
(QA-0001 Q08).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cliff.engine.pool import PortAllocator, WorkspaceProcessPool

if TYPE_CHECKING:
    from pathlib import Path


def _mock_subprocess() -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    proc.stderr = None
    proc.stdout = None
    return proc


def _mock_httpx_healthy() -> AsyncMock:
    mock_response = MagicMock()
    mock_response.status_code = 200
    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture
def pool() -> WorkspaceProcessPool:
    return WorkspaceProcessPool(
        port_allocator=PortAllocator(start=5200, end=5209),
        host="127.0.0.1",
    )


async def test_npm_cache_is_per_workspace_no_crosstalk(
    pool: WorkspaceProcessPool, tmp_path: Path
):
    """Two workspaces ⇒ two distinct NPM_CONFIG_CACHE paths, each
    rooted inside that workspace's dir. Neither leaks into the other."""
    ws_a = tmp_path / "ws-a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws-b"
    ws_b.mkdir()

    captured_envs: list[dict[str, str]] = []

    async def _capture_subprocess(*_args, **kwargs):
        captured_envs.append(dict(kwargs.get("env") or {}))
        return _mock_subprocess()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=_capture_subprocess),
        ),
        patch(
            "cliff.engine.pool.httpx.AsyncClient",
            return_value=_mock_httpx_healthy(),
        ),
    ):
        await pool.start("ws-a", ws_a)
        await pool.start("ws-b", ws_b)

    assert len(captured_envs) == 2

    cache_a = captured_envs[0]["NPM_CONFIG_CACHE"]
    cache_b = captured_envs[1]["NPM_CONFIG_CACHE"]

    # Each subprocess sees its own cache, rooted inside its workspace dir.
    assert cache_a == str(ws_a / ".npm-cache")
    assert cache_b == str(ws_b / ".npm-cache")
    assert cache_a != cache_b

    # And the cache dirs were materialized on disk.
    assert (ws_a / ".npm-cache").is_dir()
    assert (ws_b / ".npm-cache").is_dir()

    # Sanity: the cache for A is not under B's tree (no crosstalk).
    assert ws_b not in (ws_a / ".npm-cache").parents
    assert ws_a not in (ws_b / ".npm-cache").parents
