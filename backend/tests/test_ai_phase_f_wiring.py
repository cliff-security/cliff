"""Phase F integration tests — env injection + opencode.json model + restart hook.

These exercise the cross-vertical seams between ``AIIntegrationService``,
``WorkspaceProcessPool`` (env injection), ``WorkspaceDirManager`` (model
in rendered ``opencode.json``), and the singleton restart hook. No real
OpenCode subprocess — we mock at the subprocess boundary.
"""

from __future__ import annotations

import json
import os
import socket
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from opensec.ai.service import AIIntegrationService
from opensec.db.connection import close_db, init_db
from opensec.engine.pool import WorkspaceProcessPool
from opensec.integrations.vault import CredentialVault
from opensec.workspace.workspace_dir_manager import WorkspaceDirManager

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


# ---------------------------------------------------------------------------
# F1: opencode.json renders model from active integration
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
def vault(db: aiosqlite.Connection) -> CredentialVault:
    return CredentialVault(db, key=os.urandom(32))


def _make_finding():
    from datetime import UTC, datetime

    from opensec.models import Finding

    now = datetime.now(UTC).isoformat()
    return Finding(
        id="f-1",
        source_type="test",
        source_id="t1",
        title="Test finding",
        status="new",
        created_at=now,
        updated_at=now,
    )


async def test_dir_manager_writes_model_when_provided(tmp_path: Path) -> None:
    mgr = WorkspaceDirManager(base_dir=tmp_path)
    ws = mgr.create("ws-1", _make_finding(), model="claude-sonnet-4-6")
    config = json.loads(ws.opencode_json.read_text())
    assert config["model"] == "claude-sonnet-4-6"


async def test_dir_manager_omits_model_when_none(tmp_path: Path) -> None:
    mgr = WorkspaceDirManager(base_dir=tmp_path)
    ws = mgr.create("ws-2", _make_finding())
    config = json.loads(ws.opencode_json.read_text())
    assert "model" not in config


async def test_opencode_json_never_contains_raw_key(tmp_path: Path) -> None:
    """Guardrail: no matter what we pass, the rendered file holds no key."""
    mgr = WorkspaceDirManager(base_dir=tmp_path)
    ws = mgr.create("ws-3", _make_finding(), model="claude-sonnet-4-6")
    body = ws.opencode_json.read_text()
    # No sk- keys, no api_key field.
    assert "sk-" not in body
    assert "api_key" not in body.lower()
    assert "anthropic_api_key" not in body.lower()


# ---------------------------------------------------------------------------
# F2: pool env_resolver merges into the subprocess env
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_pool_calls_env_resolver_on_start(tmp_path: Path) -> None:
    """The resolver is awaited and its result merged into the spawned env."""
    called: list = []

    async def resolver() -> dict[str, str]:
        called.append(True)
        return {"ANTHROPIC_API_KEY": "sk-ant-from-resolver"}

    pool = WorkspaceProcessPool(env_resolver=resolver)
    captured_env = {}

    async def fake_subprocess(*args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        proc = AsyncMock()
        proc.returncode = None
        proc.terminate = lambda: None
        proc.kill = lambda: None
        proc.wait = AsyncMock(return_value=0)
        proc.stderr = None
        return proc

    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_subprocess,
        ),
        patch.object(pool, "_wait_for_healthy", new=AsyncMock()),
    ):
        try:
            await pool.start("ws-1", workspace_dir)
        finally:
            await pool.stop_all()

    assert called, "env_resolver was not awaited"
    assert captured_env.get("ANTHROPIC_API_KEY") == "sk-ant-from-resolver"


async def test_pool_resolver_failure_does_not_block_spawn(tmp_path: Path) -> None:
    """A resolver crash must not stop the spawn — log + skip its env."""

    async def boom() -> dict[str, str]:
        raise RuntimeError("vault unavailable")

    pool = WorkspaceProcessPool(env_resolver=boom)
    captured_env = {}

    async def fake_subprocess(*args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        proc = AsyncMock()
        proc.returncode = None
        proc.terminate = lambda: None
        proc.kill = lambda: None
        proc.wait = AsyncMock(return_value=0)
        proc.stderr = None
        return proc

    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_subprocess,
        ),
        patch.object(pool, "_wait_for_healthy", new=AsyncMock()),
    ):
        try:
            await pool.start("ws-1", workspace_dir)
        finally:
            await pool.stop_all()

    # Spawn succeeded; AI env absent.
    assert "ANTHROPIC_API_KEY" not in captured_env
    assert "OPENROUTER_API_KEY" not in captured_env


async def test_pool_merges_caller_env_on_top_of_resolver(tmp_path: Path) -> None:
    """Caller-supplied env_vars override resolver output (last-write wins)."""

    async def resolver() -> dict[str, str]:
        return {"ANTHROPIC_API_KEY": "from-resolver"}

    pool = WorkspaceProcessPool(env_resolver=resolver)
    captured_env = {}

    async def fake_subprocess(*args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        proc = AsyncMock()
        proc.returncode = None
        proc.terminate = lambda: None
        proc.kill = lambda: None
        proc.wait = AsyncMock(return_value=0)
        proc.stderr = None
        return proc

    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_subprocess,
        ),
        patch.object(pool, "_wait_for_healthy", new=AsyncMock()),
    ):
        try:
            await pool.start(
                "ws-1",
                workspace_dir,
                env_vars={"ANTHROPIC_API_KEY": "from-caller", "GH_TOKEN": "ghp_xyz"},
            )
        finally:
            await pool.stop_all()

    assert captured_env["ANTHROPIC_API_KEY"] == "from-caller"
    assert captured_env["GH_TOKEN"] == "ghp_xyz"


# ---------------------------------------------------------------------------
# F3: on_key_change hook fires with fresh env after every save/disconnect
# ---------------------------------------------------------------------------


async def test_on_key_change_fires_with_correct_env_after_save(
    db: aiosqlite.Connection, vault: CredentialVault
) -> None:
    captured: list[dict[str, str]] = []

    async def on_change(env: dict[str, str]) -> None:
        captured.append(env)

    service = AIIntegrationService(db, vault, on_key_change=on_change)
    await service.save_byok("anthropic", "sk-ant-saved")
    assert captured == [{"ANTHROPIC_API_KEY": "sk-ant-saved"}]


async def test_on_key_change_fires_empty_after_disconnect(
    db: aiosqlite.Connection, vault: CredentialVault
) -> None:
    captured: list[dict[str, str]] = []

    async def on_change(env: dict[str, str]) -> None:
        captured.append(env)

    service = AIIntegrationService(db, vault, on_key_change=on_change)
    await service.save_byok("anthropic", "sk-ant-saved")
    await service.disconnect()
    assert captured[-1] == {}


async def test_on_key_change_failure_does_not_break_save(
    db: aiosqlite.Connection, vault: CredentialVault
) -> None:
    async def explode(_env: dict[str, str]) -> None:
        raise RuntimeError("singleton restart failed")

    service = AIIntegrationService(db, vault, on_key_change=explode)
    # Save still succeeds.
    record = await service.save_byok("anthropic", "sk-ant-saved")
    assert record.provider == "anthropic"
