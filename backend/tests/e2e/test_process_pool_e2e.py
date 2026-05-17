"""E2E tests for WorkspaceProcessPool with real OpenCode processes.

These tests start actual OpenCode subprocesses on real ports. They verify
process lifecycle, multi-workspace isolation, port management, and failure
modes under real conditions.

Requires:
  - OpenCode binary installed
  - OPENAI_API_KEY (or another provider key) set in the environment

Auto-skipped if prerequisites are missing (via e2e/conftest.py markers).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cliff.agents import AgentTemplateEngine
from cliff.engine.pool import PortAllocator, WorkspaceProcessPool
from cliff.models import Finding
from cliff.workspace import WorkspaceDirManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_finding(finding_id: str, title: str) -> Finding:
    """Create a Finding model for workspace directory setup."""
    now = datetime.now(UTC)
    return Finding(
        id=finding_id,
        source_type="test",
        source_id=f"test-{finding_id}",
        title=title,
        description=f"Test finding: {title}",
        raw_severity="high",
        asset_id="test-asset",
        asset_label="test-asset",
        status="new",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def dir_manager(tmp_path: Path) -> WorkspaceDirManager:
    return WorkspaceDirManager(base_dir=tmp_path / "workspaces")


@pytest.fixture
def template_engine() -> AgentTemplateEngine:
    return AgentTemplateEngine()


def _create_workspace_dir(
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
    workspace_id: str,
    finding: Finding,
) -> Path:
    """Create a real workspace directory with finding context and agent templates."""
    ws = dir_manager.create(workspace_id, finding)
    finding_dict = finding.model_dump(mode="json")
    template_engine.write_agents(ws.agents_dir, finding=finding_dict)
    return ws.root


@pytest.fixture
async def pool():
    """Process pool using ports 4200-4220 to avoid conflicts."""
    p = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=4200, end=4220),
    )
    yield p
    await p.stop_all()


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------


async def test_start_single_workspace_process(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Start one workspace process, verify it's healthy and responds."""
    finding = _make_finding("f-001", "Log4j RCE (CVE-2021-44228)")
    ws_dir = _create_workspace_dir(dir_manager, template_engine, "ws-e2e-1", finding)

    client = await pool.start("ws-e2e-1", ws_dir)
    assert client is not None

    # Verify the process responds to health checks
    healthy = await client.health_check()
    assert healthy is True

    # Verify we can create a session
    session = await client.create_session()
    assert session.id

    # Verify status
    status = pool.status()
    assert status["active_processes"] == 1
    assert "ws-e2e-1" in status["workspaces"]


async def test_start_and_stop_releases_resources(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Start, stop, verify port is reusable."""
    finding = _make_finding("f-002", "TLS cert expired")
    ws_dir = _create_workspace_dir(dir_manager, template_engine, "ws-e2e-2", finding)

    await pool.start("ws-e2e-2", ws_dir)
    port_used = pool._processes["ws-e2e-2"].port

    await pool.stop("ws-e2e-2")

    # Port should be freed — start another workspace, should get same port
    finding2 = _make_finding("f-003", "SQL injection")
    ws_dir2 = _create_workspace_dir(dir_manager, template_engine, "ws-e2e-3", finding2)
    await pool.start("ws-e2e-3", ws_dir2)
    assert pool._processes["ws-e2e-3"].port == port_used


async def test_health_check_on_workspace_process(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Verify health check works on a workspace process."""
    finding = _make_finding("f-004", "Weak cipher suite")
    ws_dir = _create_workspace_dir(dir_manager, template_engine, "ws-e2e-4", finding)

    client = await pool.start("ws-e2e-4", ws_dir)
    assert await client.health_check() is True


async def test_process_crash_recovery(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Kill a process externally, verify get_or_start restarts it."""
    finding = _make_finding("f-005", "Open redirect")
    ws_dir = _create_workspace_dir(dir_manager, template_engine, "ws-e2e-5", finding)

    await pool.start("ws-e2e-5", ws_dir)
    # Kill the process externally
    proc = pool._processes["ws-e2e-5"].process
    assert proc is not None
    proc.kill()
    await proc.wait()

    # get_or_start should detect the dead process and restart
    client = await pool.get_or_start("ws-e2e-5", ws_dir)
    assert client is not None
    assert await client.health_check() is True


# ---------------------------------------------------------------------------
# Multi-workspace
# ---------------------------------------------------------------------------


async def test_three_concurrent_workspaces(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Start 3 workspaces concurrently, verify all respond independently."""
    findings = [
        _make_finding("f-c1", "Log4j RCE"),
        _make_finding("f-c2", "Expired TLS cert"),
        _make_finding("f-c3", "SQL injection in login"),
    ]
    ws_dirs = [
        _create_workspace_dir(dir_manager, template_engine, f"ws-conc-{i}", f)
        for i, f in enumerate(findings)
    ]

    # Start all 3 concurrently
    clients = await asyncio.gather(
        *(pool.start(f"ws-conc-{i}", ws_dirs[i]) for i in range(3))
    )

    assert len(clients) == 3

    # All should be healthy
    health_results = await asyncio.gather(*(c.health_check() for c in clients))
    assert all(health_results)

    # All should have different ports
    ports = {pool._processes[f"ws-conc-{i}"].port for i in range(3)}
    assert len(ports) == 3

    # All should be able to create sessions
    sessions = await asyncio.gather(*(c.create_session() for c in clients))
    session_ids = {s.id for s in sessions}
    assert len(session_ids) == 3  # all unique


async def test_ten_workspaces_sequential(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Create 10 workspaces sequentially, verify all work, then stop all."""
    clients = []
    for i in range(10):
        finding = _make_finding(f"f-seq-{i}", f"Finding #{i}")
        ws_dir = _create_workspace_dir(
            dir_manager, template_engine, f"ws-seq-{i}", finding
        )
        client = await pool.start(f"ws-seq-{i}", ws_dir)
        clients.append(client)

    # All 10 should be running
    assert pool.status()["active_processes"] == 10

    # All should respond to health checks
    for client in clients:
        assert await client.health_check() is True

    # Stop all
    await pool.stop_all()
    assert pool.status()["active_processes"] == 0
    assert pool._ports.available == pool._ports.total


async def test_four_concurrent_workspaces_have_isolated_npm_caches(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """EF-B15 regression: 4 concurrent pool spawns each materialize a
    distinct ``.npm-cache`` directory under their own workspace dir.

    Before the fix, all 4 workspaces shared ``~/.npm`` and concurrent
    ``npm install`` invocations contended on the same lockfile, driving
    load average to 17-20 and triggering the OpenCode retry storm. The
    pool now sets ``NPM_CONFIG_CACHE`` to ``<workspace>/.npm-cache``
    per spawn, eliminating the contention.
    """
    findings = [_make_finding(f"f-npm-{i}", f"npm cache #{i}") for i in range(4)]
    ws_dirs = [
        _create_workspace_dir(dir_manager, template_engine, f"ws-npm-{i}", f)
        for i, f in enumerate(findings)
    ]

    clients = await asyncio.gather(
        *(pool.start(f"ws-npm-{i}", ws_dirs[i]) for i in range(4))
    )
    assert len(clients) == 4

    # Each workspace must have its own cache dir on disk.
    cache_dirs = [d / ".npm-cache" for d in ws_dirs]
    for d in cache_dirs:
        assert d.is_dir(), f"missing per-workspace npm cache: {d}"

    # The 4 cache paths must be distinct (no cross-talk).
    assert len({str(p) for p in cache_dirs}) == 4

    # And no cache dir lives inside another workspace's tree.
    for i, d in enumerate(ws_dirs):
        for j, c in enumerate(cache_dirs):
            if i == j:
                continue
            assert d not in c.parents, f"workspace {j}'s cache leaked into ws {i}"


async def test_concurrent_get_or_start_same_workspace(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """5 concurrent get_or_start for the same workspace — only 1 process starts."""
    finding = _make_finding("f-lock", "Race condition test")
    ws_dir = _create_workspace_dir(dir_manager, template_engine, "ws-lock", finding)

    # Fire 5 concurrent requests
    results = await asyncio.gather(
        *(pool.get_or_start("ws-lock", ws_dir) for _ in range(5))
    )

    # All should return the same client
    assert all(r is results[0] for r in results)

    # Only 1 process in the pool
    assert pool.status()["active_processes"] == 1


# ---------------------------------------------------------------------------
# Port exhaustion
# ---------------------------------------------------------------------------


async def test_port_exhaustion_raises(
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Exhaust the port range, verify clear error."""
    small_pool = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=4250, end=4252),
    )
    try:
        for i in range(3):
            finding = _make_finding(f"f-exh-{i}", f"Exhaustion #{i}")
            ws_dir = _create_workspace_dir(
                dir_manager, template_engine, f"ws-exh-{i}", finding
            )
            await small_pool.start(f"ws-exh-{i}", ws_dir)

        # 4th should fail
        finding = _make_finding("f-exh-3", "One too many")
        ws_dir = _create_workspace_dir(
            dir_manager, template_engine, "ws-exh-3", finding
        )
        with pytest.raises(RuntimeError, match="No free ports"):
            await small_pool.start("ws-exh-3", ws_dir)
    finally:
        await small_pool.stop_all()


async def test_port_reuse_after_stop(
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Exhaust ports, stop one, verify next start succeeds."""
    small_pool = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=4260, end=4262),
    )
    try:
        for i in range(3):
            finding = _make_finding(f"f-reuse-{i}", f"Reuse #{i}")
            ws_dir = _create_workspace_dir(
                dir_manager, template_engine, f"ws-reuse-{i}", finding
            )
            await small_pool.start(f"ws-reuse-{i}", ws_dir)

        # Stop one
        await small_pool.stop("ws-reuse-1")

        # Now we can start another
        finding = _make_finding("f-reuse-new", "After reuse")
        ws_dir = _create_workspace_dir(
            dir_manager, template_engine, "ws-reuse-new", finding
        )
        client = await small_pool.start("ws-reuse-new", ws_dir)
        assert await client.health_check() is True
    finally:
        await small_pool.stop_all()


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


async def test_stop_idle_only_stops_old_processes(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Only idle processes are stopped."""
    for i in range(2):
        finding = _make_finding(f"f-idle-{i}", f"Idle test #{i}")
        ws_dir = _create_workspace_dir(
            dir_manager, template_engine, f"ws-idle-{i}", finding
        )
        await pool.start(f"ws-idle-{i}", ws_dir)

    # Make ws-idle-0 appear old
    import time

    pool._processes["ws-idle-0"].last_activity = time.monotonic() - 999

    stopped = await pool.stop_idle(timedelta(seconds=10))

    assert "ws-idle-0" in stopped
    assert "ws-idle-1" not in stopped
    assert pool.status()["active_processes"] == 1
