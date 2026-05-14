"""WorkspaceProcessPool — manages per-workspace OpenCode subprocesses."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from opensec.ai import catalog as ai_catalog
from opensec.config import settings
from opensec.engine.client import OpenCodeClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import timedelta
    from pathlib import Path

logger = logging.getLogger(__name__)

# AI provider env var → OpenCode provider id, derived from the AI catalog so
# the provider list has exactly one home. ``custom`` is excluded: it shares
# ``OPENAI_API_KEY`` and ships no OpenCode provider config of its own. See
# ``_push_ai_auth`` for why the pool pushes these at all.
_AI_ENV_VAR_TO_PROVIDER_ID: dict[str, str] = {
    ai_catalog.env_var_name(p): p
    for p in ai_catalog.all_providers()
    if p != "custom"
}


def _archive_and_remove(src: Path, dest: Path, arcname: str) -> None:
    """Create a gzipped tarball at ``dest`` and remove ``src``. Blocking.

    The tarball is written to ``<dest>.tmp`` first and renamed into place
    only after the gzip stream is closed, so a mid-archive crash leaves
    either (a) the original source dir intact, or (b) the final archive —
    never a truncated ``.tar.gz`` next to an intact source dir.
    """
    tmp_dest = dest.with_name(dest.name + ".tmp")
    try:
        with tarfile.open(tmp_dest, "w:gz") as tar:
            tar.add(src, arcname=arcname)
        os.replace(tmp_dest, dest)
    except BaseException:
        # Clean up a partial tarball so a retry starts from a clean slate.
        tmp_dest.unlink(missing_ok=True)
        raise
    shutil.rmtree(src)


class PortAllocator:
    """Simple set-based port allocator for workspace processes."""

    def __init__(self, start: int = 4100, end: int = 4199) -> None:
        self._range_start = start
        self._range_end = end
        self._used: set[int] = set()

    def allocate(self) -> int:
        """Return the first free port in the range.

        Raises:
            RuntimeError: If all ports in the range are in use.
        """
        for port in range(self._range_start, self._range_end + 1):
            if port not in self._used:
                self._used.add(port)
                return port
        raise RuntimeError(
            f"No free ports in range {self._range_start}-{self._range_end} "
            f"({len(self._used)} in use)"
        )

    def release(self, port: int) -> None:
        """Release a port back to the pool."""
        self._used.discard(port)

    @property
    def available(self) -> int:
        """Number of ports still available."""
        return (self._range_end - self._range_start + 1) - len(self._used)

    @property
    def total(self) -> int:
        return self._range_end - self._range_start + 1


@dataclass
class WorkspaceProcess:
    """Tracks a single workspace's OpenCode subprocess."""

    workspace_id: str
    workspace_dir: Path
    port: int
    process: asyncio.subprocess.Process | None = None
    client: OpenCodeClient | None = None
    last_activity: float = field(default_factory=time.monotonic)
    _healthy: bool = False

    def touch(self) -> None:
        """Update last_activity timestamp."""
        self.last_activity = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_activity

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def base_url(self) -> str:
        return f"http://{settings.opencode_host}:{self.port}"


class WorkspaceProcessPool:
    """Manages per-workspace OpenCode processes.

    Each workspace gets its own OpenCode subprocess running with
    ``cwd=workspace_dir`` so the AI engine only sees the workspace's
    context files, agent definitions, and CONTEXT.md.
    """

    def __init__(
        self,
        port_allocator: PortAllocator | None = None,
        host: str | None = None,
        *,
        env_resolver: Callable[[], Awaitable[dict[str, str]]] | None = None,
    ) -> None:
        """Create a process pool.

        ``env_resolver`` (ADR-0036 / IMPL-0011) — an optional async callable
        invoked before every ``start()``. Its return value is merged into
        the per-workspace subprocess environment, on top of any caller-
        supplied ``env_vars``. Used to inject the active AI provider key
        (e.g. ``OPENROUTER_API_KEY``) without every call site needing to
        know about the AI integration service.
        """
        self._processes: dict[str, WorkspaceProcess] = {}
        self._ports = port_allocator or PortAllocator(
            settings.opencode_port_range_start,
            settings.opencode_port_range_end,
        )
        self._host = host or settings.opencode_host
        self._locks: dict[str, asyncio.Lock] = {}
        self._env_resolver = env_resolver

    def _get_lock(self, workspace_id: str) -> asyncio.Lock:
        if workspace_id not in self._locks:
            self._locks[workspace_id] = asyncio.Lock()
        return self._locks[workspace_id]

    # ------------------------------------------------------------------
    # Start / get
    # ------------------------------------------------------------------

    async def start(
        self,
        workspace_id: str,
        workspace_dir: Path,
        *,
        env_vars: dict[str, str] | None = None,
    ) -> OpenCodeClient:
        """Start a new OpenCode process for a workspace.

        Allocates a port, launches the subprocess with ``cwd=workspace_dir``,
        waits for it to become healthy, and returns an ``OpenCodeClient``
        bound to that instance.

        Args:
            workspace_id: Unique workspace identifier.
            workspace_dir: Working directory for the subprocess.
            env_vars: Extra environment variables to inject (e.g. GH_TOKEN).
                Merged with the current process environment. Pass None or
                empty dict to inherit the parent environment unchanged.

        Raises:
            RuntimeError: If no ports are available or the process fails to start.
            TimeoutError: If the process doesn't become healthy in time.
        """
        binary = settings.opencode_binary_path
        port = self._ports.allocate()

        # Pull in env from the resolver (typically the AI provider key) so
        # every caller picks it up automatically without needing to know
        # about the AI integration service.
        merged_env_vars: dict[str, str] = {}
        if self._env_resolver is not None:
            try:
                resolver_env = await self._env_resolver()
            except Exception:  # noqa: BLE001 — never crash spawns over env enrichment
                logger.warning(
                    "AI env resolver failed for workspace %s; spawning without it",
                    workspace_id,
                    exc_info=True,
                )
                resolver_env = {}
            merged_env_vars.update(resolver_env)
        if env_vars:
            merged_env_vars.update(env_vars)

        # ----------------------------------------------------------------
        # Workspace-isolation guard (post-mortem fix).
        #
        # The remediation agent runs ``git``/``gh`` itself (ADR-0024) and is
        # *supposed* to operate only inside ``<workspace_dir>/repo/``. But
        # ``git`` searches parent directories for ``.git`` — so if the
        # agent's clone is missing/partial (``repo/`` exists with files but
        # no ``.git``) and it runs ``git checkout``/``commit``/``reset``,
        # git walks UP the tree and finds whatever repository the workspace
        # dir happens to be nested inside. In a dev worktree (or a user
        # securing their own checkout) that's the developer's working tree
        # — and ``git reset --hard`` there is silent, unrecoverable data
        # loss. This actually happened: a urllib3 remediation hijacked the
        # dev worktree onto its fix branch and reset --hard wiped hours of
        # uncommitted work.
        #
        # ``GIT_CEILING_DIRECTORIES`` makes git physically refuse to chdir
        # above the workspace dir when searching for a repository. The
        # happy path is unaffected (``repo/.git`` is found immediately);
        # the escape path now fails loudly with "not a git repository"
        # instead of silently operating on the parent repo.
        merged_env_vars["GIT_CEILING_DIRECTORIES"] = str(workspace_dir)

        # Merge extra env vars with system environment.
        env = {**os.environ, **merged_env_vars}
        if merged_env_vars:
            logger.info(
                "Injecting env vars for workspace %s: %s",
                workspace_id,
                list(merged_env_vars.keys()),
            )

        try:
            process = await asyncio.create_subprocess_exec(
                str(binary),
                "serve",
                "--port",
                str(port),
                "--hostname",
                self._host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace_dir),
                env=env,
            )

            wp = WorkspaceProcess(
                workspace_id=workspace_id,
                workspace_dir=workspace_dir,
                port=port,
                process=process,
            )

            await self._wait_for_healthy(wp, timeout=30.0)

            wp.client = OpenCodeClient(base_url=wp.base_url)
            wp._healthy = True

            # Push AI auth *before* publishing to ``self._processes``: the
            # ``get_or_start`` fast path reads that dict outside the per-
            # workspace lock, so a concurrent caller must not be handed a
            # client whose OpenCode process hasn't been authenticated yet.
            await self._push_ai_auth(wp, merged_env_vars)
            self._processes[workspace_id] = wp

            logger.info(
                "Started workspace process %s on port %d (cwd=%s)",
                workspace_id,
                port,
                workspace_dir,
            )
            return wp.client

        except Exception:
            self._ports.release(port)
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            raise

    async def get_or_start(
        self,
        workspace_id: str,
        workspace_dir: Path,
        *,
        env_vars: dict[str, str] | None = None,
    ) -> OpenCodeClient:
        """Return existing client or start a new process.

        This is the main entry point. Uses a per-workspace lock to prevent
        double-start race conditions from concurrent requests.

        Note: ``env_vars`` are only applied when a *new* process is started.
        Already-running processes keep their original environment.
        """
        # Fast path: already running
        wp = self._processes.get(workspace_id)
        if wp and wp.is_running and wp.client:
            wp.touch()
            return wp.client

        # Slow path: acquire lock and start
        async with self._get_lock(workspace_id):
            # Re-check after lock (another request may have started it)
            wp = self._processes.get(workspace_id)
            if wp and wp.is_running and wp.client:
                wp.touch()
                return wp.client

            # Clean up dead process if exists
            if wp:
                await self._cleanup(workspace_id)

            return await self.start(workspace_id, workspace_dir, env_vars=env_vars)

    async def get(self, workspace_id: str) -> OpenCodeClient | None:
        """Return client for an already-running workspace, or None."""
        wp = self._processes.get(workspace_id)
        if wp and wp.is_running and wp.client:
            wp.touch()
            return wp.client
        return None

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    async def stop(self, workspace_id: str) -> None:
        """Stop a workspace's OpenCode process and release its port."""
        wp = self._processes.pop(workspace_id, None)
        if wp is None:
            return

        if wp.client:
            await wp.client.close()

        if wp.process and wp.process.returncode is None:
            wp.process.terminate()
            try:
                await asyncio.wait_for(wp.process.wait(), timeout=10.0)
            except TimeoutError:
                logger.warning(
                    "Workspace process %s did not stop gracefully, killing",
                    workspace_id,
                )
                wp.process.kill()
                await wp.process.wait()

        self._ports.release(wp.port)
        self._locks.pop(workspace_id, None)
        logger.info("Stopped workspace process %s (port %d)", workspace_id, wp.port)

    async def stop_all(self) -> None:
        """Stop all managed processes. Called at application shutdown."""
        workspace_ids = list(self._processes.keys())
        for ws_id in workspace_ids:
            await self.stop(ws_id)

    async def stop_on_completion(self, workspace_id: str) -> Path | None:
        """Stop a repo-action workspace, archive its directory, and remove it.

        Idempotent — returns ``None`` when the workspace is unknown so
        callers (e.g. the Session-B posture-fix route) can invoke it freely
        after PR verification. Archival runs in a worker thread because
        tar-gzipping a cloned repo can block for seconds.
        """
        wp = self._processes.get(workspace_id)
        workspace_dir: Path | None = wp.workspace_dir if wp else None

        await self.stop(workspace_id)

        if workspace_dir is None or not workspace_dir.exists():
            return None

        archive_path = workspace_dir.parent / f"{workspace_id}.tar.gz"
        await asyncio.to_thread(
            _archive_and_remove, workspace_dir, archive_path, workspace_id
        )
        logger.info(
            "Archived repo-action workspace %s to %s",
            workspace_id,
            archive_path,
        )
        return archive_path

    async def stop_idle(self, max_idle: timedelta) -> list[str]:
        """Stop processes idle longer than max_idle.

        Returns list of stopped workspace IDs.
        """
        max_idle_seconds = max_idle.total_seconds()
        to_stop = [
            ws_id
            for ws_id, wp in self._processes.items()
            if wp.idle_seconds > max_idle_seconds
        ]
        for ws_id in to_stop:
            await self.stop(ws_id)
        if to_stop:
            logger.info("Idle cleanup stopped %d processes: %s", len(to_stop), to_stop)
        return to_stop

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return pool status for health/debug endpoints."""
        return {
            "active_processes": len(self._processes),
            "available_ports": self._ports.available,
            "total_ports": self._ports.total,
            "workspaces": {
                ws_id: {
                    "port": wp.port,
                    "workspace_dir": str(wp.workspace_dir),
                    "idle_seconds": round(wp.idle_seconds, 1),
                    "is_running": wp.is_running,
                }
                for ws_id, wp in self._processes.items()
            },
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _wait_for_healthy(
        self, wp: WorkspaceProcess, timeout: float = 30.0
    ) -> None:
        """Poll until the workspace's OpenCode server responds."""
        url = f"{wp.base_url}/session"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=2.0)
                    if resp.status_code < 500:
                        return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

            # Check if process died
            if wp.process and wp.process.returncode is not None:
                stderr = ""
                if wp.process.stderr:
                    stderr_bytes = await wp.process.stderr.read()
                    stderr = stderr_bytes.decode(errors="replace")
                raise RuntimeError(
                    f"Workspace process {wp.workspace_id} exited with code "
                    f"{wp.process.returncode}: {stderr}"
                )
            await asyncio.sleep(0.5)

        raise TimeoutError(
            f"Workspace process {wp.workspace_id} did not become healthy "
            f"within {timeout}s on port {wp.port}"
        )

    async def _push_ai_auth(
        self, wp: WorkspaceProcess, env_vars: dict[str, str]
    ) -> None:
        """Register injected AI provider keys with the workspace's OpenCode.

        OpenCode authenticates outbound provider calls from its ``/auth``
        store. The bare env var alone is not enough on OpenCode 1.3.x — so
        for every AI provider key the pool injected into this subprocess we
        also push it through ``PUT /auth/{id}`` against the workspace's own
        process. Best-effort: a failure here is warning-logged and the env
        var injection remains as a fallback, exactly as on the singleton.
        """
        if wp.client is None:
            return
        for env_var, provider_id in _AI_ENV_VAR_TO_PROVIDER_ID.items():
            key = env_vars.get(env_var)
            if not key:
                continue
            try:
                await wp.client.set_auth(
                    provider_id, {"type": "api", "key": key}
                )
            except Exception:  # noqa: BLE001 — never block a spawn on auth push
                logger.warning(
                    "Could not push %s auth to workspace process %s "
                    "(env-var injection remains as fallback)",
                    provider_id,
                    wp.workspace_id,
                    exc_info=True,
                )

    async def _cleanup(self, workspace_id: str) -> None:
        """Clean up a dead process entry without logging as a 'stop'."""
        wp = self._processes.pop(workspace_id, None)
        if wp:
            if wp.client:
                await wp.client.close()
            self._ports.release(wp.port)
