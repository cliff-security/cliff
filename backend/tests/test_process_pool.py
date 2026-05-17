"""Tests for Layer 3: WorkspaceProcessPool, PortAllocator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cliff.engine.pool import PortAllocator, WorkspaceProcess, WorkspaceProcessPool

# ---------------------------------------------------------------------------
# PortAllocator
# ---------------------------------------------------------------------------


def test_allocate_returns_first_port():
    pa = PortAllocator(start=5000, end=5009)
    assert pa.allocate() == 5000


def test_allocate_sequential():
    pa = PortAllocator(start=5000, end=5009)
    assert pa.allocate() == 5000
    assert pa.allocate() == 5001
    assert pa.allocate() == 5002


def test_release_makes_port_available():
    pa = PortAllocator(start=5000, end=5009)
    port = pa.allocate()
    pa.release(port)
    assert pa.allocate() == port


def test_allocate_exhausted():
    pa = PortAllocator(start=5000, end=5002)
    pa.allocate()
    pa.allocate()
    pa.allocate()
    with pytest.raises(RuntimeError, match="No free ports"):
        pa.allocate()


def test_available_count():
    pa = PortAllocator(start=5000, end=5004)
    assert pa.available == 5
    pa.allocate()
    assert pa.available == 4
    pa.allocate()
    pa.release(5000)
    assert pa.available == 4


# ---------------------------------------------------------------------------
# WorkspaceProcess
# ---------------------------------------------------------------------------


def test_workspace_process_idle_seconds():
    wp = WorkspaceProcess(
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        port=5000,
    )
    assert wp.idle_seconds >= 0


def test_workspace_process_touch():
    wp = WorkspaceProcess(
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        port=5000,
    )
    import time

    time.sleep(0.05)
    idle_before = wp.idle_seconds
    wp.touch()
    idle_after = wp.idle_seconds
    assert idle_after < idle_before


def test_workspace_process_is_running():
    wp = WorkspaceProcess(
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        port=5000,
    )
    assert wp.is_running is False

    mock_proc = MagicMock()
    mock_proc.returncode = None
    wp.process = mock_proc
    assert wp.is_running is True

    mock_proc.returncode = 0
    assert wp.is_running is False


# ---------------------------------------------------------------------------
# WorkspaceProcessPool (mocked subprocess + httpx)
# ---------------------------------------------------------------------------


def _make_mock_subprocess():
    """Create a mock asyncio subprocess."""
    proc = AsyncMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    proc.stderr = None
    proc.stdout = None
    return proc


def _make_mock_httpx_healthy():
    """Create a mock httpx context manager that returns 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.fixture
def pool():
    """Process pool with a small port range for testing."""
    return WorkspaceProcessPool(
        port_allocator=PortAllocator(start=5100, end=5109),
        host="127.0.0.1",
    )


async def test_start_allocates_port_and_starts_process(pool: WorkspaceProcessPool):
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        client = await pool.start("ws-1", Path("/tmp/ws-1"))

    assert client is not None
    assert client.base_url == "http://127.0.0.1:5100"

    # Verify subprocess was called with correct cwd
    call_kwargs = mock_exec.call_args
    assert str(call_kwargs.kwargs.get("cwd")) == "/tmp/ws-1"


async def test_get_or_start_returns_existing(pool: WorkspaceProcessPool):
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        client1 = await pool.get_or_start("ws-1", Path("/tmp/ws-1"))
        client2 = await pool.get_or_start("ws-1", Path("/tmp/ws-1"))

    assert client1 is client2
    # Only one subprocess created
    assert mock_exec.call_count == 1


async def test_stop_terminates_and_releases_port(pool: WorkspaceProcessPool):
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-1", Path("/tmp/ws-1"))

    assert pool._ports.available == 9  # 1 of 10 used

    mock_proc.returncode = None  # still running
    await pool.stop("ws-1")

    mock_proc.terminate.assert_called_once()
    assert pool._ports.available == 10  # port released
    assert await pool.get("ws-1") is None


async def test_stop_all(pool: WorkspaceProcessPool):
    mock_httpx = _make_mock_httpx_healthy()

    procs = [_make_mock_subprocess() for _ in range(3)]

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=procs),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-1", Path("/tmp/ws-1"))
        await pool.start("ws-2", Path("/tmp/ws-2"))
        await pool.start("ws-3", Path("/tmp/ws-3"))

    assert pool._ports.available == 7

    for p in procs:
        p.returncode = None

    await pool.stop_all()

    assert pool._ports.available == 10
    assert len(pool._processes) == 0


async def test_stop_idle(pool: WorkspaceProcessPool):
    mock_httpx = _make_mock_httpx_healthy()
    procs = [_make_mock_subprocess() for _ in range(2)]

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=procs),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-old", Path("/tmp/ws-old"))
        await pool.start("ws-new", Path("/tmp/ws-new"))

    # Make ws-old appear idle by manipulating last_activity
    import time

    pool._processes["ws-old"].last_activity = time.monotonic() - 999

    for p in procs:
        p.returncode = None

    from datetime import timedelta

    stopped = await pool.stop_idle(timedelta(seconds=10))

    assert "ws-old" in stopped
    assert "ws-new" not in stopped
    assert len(pool._processes) == 1


async def test_start_failure_releases_port(pool: WorkspaceProcessPool):
    """If health check fails, port must be released."""
    mock_proc = _make_mock_subprocess()
    # Simulate process dying immediately
    mock_proc.returncode = 1
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.read = AsyncMock(return_value=b"startup failed")

    import httpx as httpx_mod

    mock_httpx = AsyncMock()
    mock_httpx.get = AsyncMock(
        side_effect=httpx_mod.ConnectError("connection refused")
    )
    mock_httpx.__aenter__ = AsyncMock(return_value=mock_httpx)
    mock_httpx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
        pytest.raises(RuntimeError, match="exited with code 1"),
    ):
        await pool.start("ws-fail", Path("/tmp/ws-fail"))

    # Port must be released even though start failed
    assert pool._ports.available == 10


# ---------------------------------------------------------------------------
# Environment variable injection
# ---------------------------------------------------------------------------


async def test_start_injects_env_vars(pool: WorkspaceProcessPool):
    """When env_vars are provided, they must be merged with os.environ."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    env_vars = {"GH_TOKEN": "ghp_test123", "CLIFF_REPO_URL": "https://github.com/org/repo"}

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
        patch("cliff.engine.pool.os") as mock_os,
    ):
        mock_os.environ = {"PATH": "/usr/bin", "HOME": "/root"}
        await pool.start("ws-env", Path("/tmp/ws-env"), env_vars=env_vars)

    call_kwargs = mock_exec.call_args
    passed_env = call_kwargs.kwargs.get("env")
    assert passed_env is not None
    assert passed_env["GH_TOKEN"] == "ghp_test123"
    assert passed_env["CLIFF_REPO_URL"] == "https://github.com/org/repo"
    # System env should also be present
    assert passed_env["PATH"] == "/usr/bin"


async def test_start_without_env_vars_injects_git_ceiling(
    pool: WorkspaceProcessPool,
):
    """Even with no caller env_vars, the workspace-isolation guard
    ``GIT_CEILING_DIRECTORIES`` is always injected (set to the workspace
    dir) so the env passed to the subprocess is never None."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-noenv", Path("/tmp/ws-noenv"))

    passed_env = mock_exec.call_args.kwargs.get("env")
    assert passed_env is not None
    assert passed_env["GIT_CEILING_DIRECTORIES"] == "/tmp/ws-noenv"


async def test_get_or_start_threads_env_vars(pool: WorkspaceProcessPool):
    """get_or_start must forward env_vars to start when creating a new process."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    env_vars = {"GH_TOKEN": "ghp_thread_test"}

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
        patch("cliff.engine.pool.os") as mock_os,
    ):
        mock_os.environ = {"PATH": "/usr/bin"}
        await pool.get_or_start("ws-thread", Path("/tmp/ws-thread"), env_vars=env_vars)

    call_kwargs = mock_exec.call_args
    passed_env = call_kwargs.kwargs.get("env")
    assert passed_env is not None
    assert passed_env["GH_TOKEN"] == "ghp_thread_test"


async def test_empty_env_vars_still_injects_git_ceiling(
    pool: WorkspaceProcessPool,
):
    """An empty env_vars dict still gets the GIT_CEILING_DIRECTORIES guard —
    the isolation guard is never optional, regardless of caller input."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-empty-env", Path("/tmp/ws-empty-env"), env_vars={})

    passed_env = mock_exec.call_args.kwargs.get("env")
    assert passed_env is not None
    assert passed_env["GIT_CEILING_DIRECTORIES"] == "/tmp/ws-empty-env"


async def test_start_injects_npm_cache(
    pool: WorkspaceProcessPool, tmp_path: Path
):
    """Each workspace gets ``NPM_CONFIG_CACHE=<workspace>/.npm-cache``
    so concurrent ``npm install`` invocations don't contend on ~/.npm
    (EF-B15). The cache dir is created on disk too."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    ws_dir = tmp_path / "ws-npm"
    ws_dir.mkdir()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-npm", ws_dir)

    passed_env = mock_exec.call_args.kwargs.get("env")
    assert passed_env is not None
    assert passed_env["NPM_CONFIG_CACHE"] == str(ws_dir / ".npm-cache")
    assert (ws_dir / ".npm-cache").is_dir()


# ---------------------------------------------------------------------------
# opencode.json model reconciliation (QA Q01 B06b)
# ---------------------------------------------------------------------------


async def test_start_reconciles_opencode_model(tmp_path: Path):
    """The pool rewrites the workspace's opencode.json `model` from the
    model_resolver before spawn. Without it OpenCode falls back to a
    built-in default that routes through the wrong provider and 401s."""
    ws_dir = tmp_path / "ws-model"
    ws_dir.mkdir()
    (ws_dir / "opencode.json").write_text(
        '{"$schema": "https://opencode.ai/config.json", '
        '"permission": {"bash": "ask"}}'
    )

    pool = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=5100, end=5109),
        host="127.0.0.1",
        model_resolver=AsyncMock(return_value="anthropic/claude-sonnet-4-6"),
    )
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-model", ws_dir)

    config = json.loads((ws_dir / "opencode.json").read_text())
    assert config["model"] == "anthropic/claude-sonnet-4-6"
    # Existing keys are preserved.
    assert config["permission"] == {"bash": "ask"}


async def test_start_without_model_resolver_leaves_opencode_json_untouched(
    tmp_path: Path,
):
    """No model_resolver wired → the pool must not touch opencode.json."""
    ws_dir = tmp_path / "ws-nomodel"
    ws_dir.mkdir()
    original = '{"permission": {"bash": "ask"}}'
    (ws_dir / "opencode.json").write_text(original)

    pool = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=5100, end=5109),
        host="127.0.0.1",
    )
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-nomodel", ws_dir)

    assert (ws_dir / "opencode.json").read_text() == original


async def test_start_model_resolver_returning_none_leaves_untouched(
    tmp_path: Path,
):
    """When no AI provider is configured the resolver returns None — the
    pool leaves opencode.json alone rather than writing `model: null`."""
    ws_dir = tmp_path / "ws-modelnone"
    ws_dir.mkdir()
    original = '{"permission": {"bash": "ask"}}'
    (ws_dir / "opencode.json").write_text(original)

    pool = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=5100, end=5109),
        host="127.0.0.1",
        model_resolver=AsyncMock(return_value=None),
    )
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-modelnone", ws_dir)

    assert (ws_dir / "opencode.json").read_text() == original


# ---------------------------------------------------------------------------
# Host AI-provider env var scrubbing (QA Q01 B07)
# ---------------------------------------------------------------------------


async def test_start_scrubs_host_ai_provider_env_vars(pool: WorkspaceProcessPool):
    """A polluted host environment (e.g. Claude Desktop exports
    ANTHROPIC_BASE_URL without /v1, plus an empty ANTHROPIC_API_KEY) must
    not leak into the workspace subprocess. The resolver's values win."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
        patch("cliff.engine.pool.os") as mock_os,
    ):
        mock_os.environ = {
            "PATH": "/usr/bin",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_API_KEY": "",  # empty host value — must not shadow
            "OPENAI_BASE_URL": "https://evil.example",
        }
        await pool.start(
            "ws-scrub",
            Path("/tmp/ws-scrub"),
            env_vars={"ANTHROPIC_API_KEY": "sk-ant-real"},
        )

    passed_env = mock_exec.call_args.kwargs.get("env")
    # Host AI-provider pollution scrubbed.
    assert "ANTHROPIC_BASE_URL" not in passed_env
    assert "OPENAI_BASE_URL" not in passed_env
    # Resolver/caller value layered back on; non-AI host env preserved.
    assert passed_env["ANTHROPIC_API_KEY"] == "sk-ant-real"
    assert passed_env["PATH"] == "/usr/bin"


async def test_start_keeps_resolver_supplied_base_url(
    pool: WorkspaceProcessPool,
):
    """A *_BASE_URL the resolver/caller explicitly supplies (BYOK custom
    endpoint) survives — only host-inherited ones are scrubbed."""
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ) as mock_exec,
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
        patch("cliff.engine.pool.os") as mock_os,
    ):
        mock_os.environ = {
            "PATH": "/usr/bin",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        }
        await pool.start(
            "ws-byok-url",
            Path("/tmp/ws-byok-url"),
            env_vars={
                "ANTHROPIC_API_KEY": "sk-ant-real",
                "ANTHROPIC_BASE_URL": "https://proxy.internal/v1",
            },
        )

    passed_env = mock_exec.call_args.kwargs.get("env")
    assert passed_env["ANTHROPIC_BASE_URL"] == "https://proxy.internal/v1"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


async def test_status(pool: WorkspaceProcessPool):
    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start("ws-1", Path("/tmp/ws-1"))

    status = pool.status()
    assert status["active_processes"] == 1
    assert status["available_ports"] == 9
    assert "ws-1" in status["workspaces"]
    assert status["workspaces"]["ws-1"]["port"] == 5100


# ---------------------------------------------------------------------------
# stop_on_completion — repo-action cleanup trigger (IMPL-0002 E4)
# ---------------------------------------------------------------------------


async def test_stop_on_completion_archives_and_releases_port(
    pool: WorkspaceProcessPool, tmp_path: Path
):
    """Stops the subprocess, releases the port, tars the workspace, removes it."""
    ws_id = "repo-security-md-abcd1234"
    ws_dir = tmp_path / ws_id
    (ws_dir / ".opencode" / "agents").mkdir(parents=True)
    (ws_dir / "opencode.json").write_text("{}")
    (ws_dir / "REPO_ACTION.md").write_text("stub")

    mock_proc = _make_mock_subprocess()
    mock_httpx = _make_mock_httpx_healthy()

    with (
        patch(
            "cliff.engine.pool.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("cliff.engine.pool.httpx.AsyncClient", return_value=mock_httpx),
    ):
        await pool.start(ws_id, ws_dir)

    assert pool._ports.available == 9
    mock_proc.returncode = None  # still running until we call stop

    archive_path = await pool.stop_on_completion(ws_id)

    # Process terminated + port freed.
    mock_proc.terminate.assert_called_once()
    assert pool._ports.available == 10
    assert await pool.get(ws_id) is None

    assert archive_path is not None
    assert archive_path.exists()
    assert archive_path.name == f"{ws_id}.tar.gz"
    assert not ws_dir.exists()


async def test_stop_on_completion_unknown_workspace_is_noop(
    pool: WorkspaceProcessPool,
):
    """Calling stop_on_completion on a workspace we never started must not raise."""
    result = await pool.stop_on_completion("never-started")
    assert result is None
    assert pool._ports.available == 10


def test_archive_and_remove_is_atomic_on_failure(tmp_path: Path):
    """A failure mid-archive must leave no partial .tar.gz at the dest path."""
    from cliff.engine.pool import _archive_and_remove

    src = tmp_path / "ws-atomic"
    src.mkdir()
    (src / "file.txt").write_text("payload")
    dest = tmp_path / "ws-atomic.tar.gz"

    class _BoomError(RuntimeError):
        pass

    with (
        patch("cliff.engine.pool.tarfile.open", side_effect=_BoomError("tar exploded")),
        pytest.raises(_BoomError),
    ):
        _archive_and_remove(src, dest, "ws-atomic")

    assert not dest.exists(), "Failed archive run left a partial tarball behind"
    assert not dest.with_name(dest.name + ".tmp").exists(), (
        "Temp archive not cleaned up on failure"
    )
    # Source dir must survive — operator can retry or inspect.
    assert src.exists()
