"""Shared utilities for background task patterns."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)


def fire_and_forget_send(
    coro: Coroutine,
    *,
    description: str = "send_message",
) -> asyncio.Task:
    """Run a coroutine as a fire-and-forget background task.

    Suppresses httpx.ReadTimeout (expected when the LLM takes a long
    time) and logs other exceptions without crashing the server.
    """

    async def _wrapper() -> None:
        with contextlib.suppress(httpx.ReadTimeout):
            await coro

    task = asyncio.create_task(_wrapper())
    task.add_done_callback(
        lambda t: logger.error(
            "Background %s failed: %s", description, t.exception()
        )
        if not t.cancelled() and t.exception()
        else None
    )
    return task
