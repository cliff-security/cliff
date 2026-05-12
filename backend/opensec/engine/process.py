"""OpenCode subprocess lifecycle manager."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import httpx

from opensec.config import settings

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class OpenCodeProcess:
    """Manages the OpenCode server subprocess."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._healthy = False
        # IMPL-0011 Phase F3: extra env vars merged into os.environ at
        # spawn time. Set via update_env() before restart() so the new
        # process picks up the active AI provider key without the
        # operator restarting OpenSec.
        self._extra_env: dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def start(self) -> None:
        """Start the OpenCode server. Auto-downloads binary if needed."""
        binary = await self._ensure_binary()

        logger.info(
            "Starting OpenCode server on %s:%d", settings.opencode_host, settings.opencode_port
        )

        env = {**os.environ, **self._extra_env} if self._extra_env else None

        self._process = await asyncio.create_subprocess_exec(
            str(binary),
            "serve",
            "--port",
            str(settings.opencode_port),
            "--hostname",
            settings.opencode_host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(settings.repo_root),
            env=env,
        )

        # Wait for server to become healthy
        await self._wait_for_healthy(timeout=30.0)
        logger.info("OpenCode server is healthy")

    def set_extra_env(self, env: dict[str, str]) -> None:
        """Replace the extra-env dict applied on next start/restart.

        Pass an empty dict to clear. The change takes effect on the next
        ``start()`` — callers needing immediate effect should ``restart()``.
        """
        self._extra_env = dict(env)

    async def restart(self) -> None:
        """Stop + start the singleton with the current extra env.

        Used by ``AIIntegrationService`` after a key change so the
        singleton OpenCode (used by ``/api/settings/providers/test`` and
        the provider catalog endpoints) picks up the new env var. The
        ~1-2s blip is documented in ADR-0036.
        """
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        """Gracefully stop the OpenCode server."""
        if self._process and self._process.returncode is None:
            logger.info("Stopping OpenCode server")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except TimeoutError:
                logger.warning("OpenCode did not stop gracefully, killing")
                self._process.kill()
                await self._process.wait()
        self._process = None
        self._healthy = False

    async def health_check(self) -> bool:
        """Check if the OpenCode server is responding."""
        try:
            async with httpx.AsyncClient() as client:
                # Use /session endpoint — /doc may 500 if config has issues
                resp = await client.get(f"{settings.opencode_url}/session", timeout=2.0)
                self._healthy = resp.status_code < 500
                return self._healthy
        except (httpx.ConnectError, httpx.TimeoutException):
            self._healthy = False
            return False

    async def _wait_for_healthy(self, timeout: float = 30.0) -> None:
        """Poll until the server responds or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.health_check():
                return
            # Check if process died
            if self._process and self._process.returncode is not None:
                stderr = ""
                if self._process.stderr:
                    stderr_bytes = await self._process.stderr.read()
                    stderr = stderr_bytes.decode(errors="replace")
                raise RuntimeError(
                    f"OpenCode process exited with code {self._process.returncode}: {stderr}"
                )
            await asyncio.sleep(0.5)
        raise TimeoutError(f"OpenCode server did not become healthy within {timeout}s")

    async def _ensure_binary(self) -> Path:
        """Check for OpenCode binary, auto-download if missing."""
        binary = settings.opencode_binary_path

        if binary.exists():
            logger.info("Found OpenCode at %s", binary)
            return binary

        logger.info("OpenCode binary not found at %s, attempting auto-download", binary)
        await self._download_binary()

        if not binary.exists():
            raise FileNotFoundError(
                f"OpenCode binary not found at {binary}. "
                f"Install manually: brew install opencode, npm i -g opencode-ai, "
                f"or run: scripts/install-opencode.sh"
            )
        return binary

    async def _download_binary(self) -> None:
        """Run the install script to download OpenCode."""
        install_script = settings.repo_root / "scripts" / "install-opencode.sh"
        if not install_script.exists():
            logger.error("Install script not found at %s", install_script)
            return

        logger.info("Downloading OpenCode v%s...", settings.opencode_version)
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(install_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(
                "Failed to download OpenCode: %s",
                stderr.decode(errors="replace"),
            )
        else:
            logger.info("OpenCode download complete: %s", stdout.decode(errors="replace").strip())


# Singleton instance
opencode_process = OpenCodeProcess()
