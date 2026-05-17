"""Integration audit logger (ADR-0017).

Events are queued in-process and written asynchronously by a background task.
If the queue is full, events fall back to synchronous writes (never dropped).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from cliff.db import repo_audit

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class AuditEvent(BaseModel):
    """Structured audit event for integration actions."""

    event_type: str  # e.g. "integration.create", "credential.store", "mcp.tool_call"
    actor_type: str = "user"  # "user", "agent", "system"
    actor_id: str | None = None
    workspace_id: str | None = None
    integration_id: str | None = None
    provider_name: str | None = None
    tool_name: str | None = None
    verb: str | None = None  # "collect", "enrich", "investigate", "update"
    action_tier: int = Field(default=0, ge=0, le=2)  # 0=read, 1=enrich, 2=mutate
    status: str = "success"  # "success", "error", "timeout", "denied"
    duration_ms: int | None = None
    parameters_hash: str | None = None  # SHA-256 of parameters, never raw values
    error_message: str | None = None
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------


def hash_parameters(params: dict[str, Any] | str | None) -> str | None:
    """Hash parameters for audit storage. Never store raw values."""
    if params is None:
        return None
    if isinstance(params, str):
        return hashlib.sha256(params.encode("utf-8")).hexdigest()
    canonical = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class AuditLogger:
    """Async, non-blocking audit logger."""

    def __init__(self, db: aiosqlite.Connection, *, max_queue_size: int = 1000) -> None:
        self._db = db
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._writer_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background writer task."""
        if self._running:
            return
        self._running = True
        self._writer_task = asyncio.create_task(self._writer_loop())
        logger.info("Audit logger started")

    async def stop(self) -> None:
        """Drain the queue and stop the writer."""
        if not self._running:
            return
        self._running = False
        # Drain remaining events.
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                await self._write_event(event)
            except asyncio.QueueEmpty:
                break
        if self._writer_task is not None:
            self._writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer_task
            self._writer_task = None
        logger.info("Audit logger stopped")

    async def log(self, event: AuditEvent) -> None:
        """Log an audit event (non-blocking). Falls back to sync if queue is full."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Audit queue full — writing synchronously")
            await self._write_event(event)

    async def _writer_loop(self) -> None:
        """Background task that consumes events from the queue."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._write_event(event)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error writing audit event")

    async def _write_event(self, event: AuditEvent) -> None:
        """Persist event to the database."""
        now = datetime.now(UTC).isoformat()
        event_dict = event.model_dump()
        event_dict["timestamp"] = now
        await repo_audit.insert_audit_event(self._db, event_dict)
