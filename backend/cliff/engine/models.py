"""Pydantic models for OpenCode API types."""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 — Pydantic needs this at runtime

from pydantic import BaseModel


class SessionSummary(BaseModel):
    id: str
    created_at: datetime | None = None


class SessionDetail(BaseModel):
    id: str
    created_at: datetime | None = None
    messages: list[MessageInfo] = []
    model: str = ""


class MessageInfo(BaseModel):
    id: str
    role: str
    content: str = ""
    created_at: datetime | None = None


class SendMessageRequest(BaseModel):
    content: str
    session_id: str


class SendMessageResponse(BaseModel):
    session_id: str
    message_id: str | None = None


class HealthStatus(BaseModel):
    cliff: str = "ok"
    opencode: str = "unknown"
    opencode_version: str = ""
    model: str = ""
    # True only when an AI provider credential is present *and* reachable by
    # the per-workspace subprocesses (i.e. it resolved into the env cache the
    # process pool injects). A configured model string alone is not enough —
    # see the BYOK auth-propagation bug. ``cliff status`` turns a False
    # here into a ``no_ai_provider_credential`` blocker.
    ai_provider_ready: bool = False


class VersionInfo(BaseModel):
    """Version handshake for the agent CLI (`cliff status`).

    `min_cli` is the lowest CLI version this server promises to speak to.
    A CLI older than this should refuse to operate and tell the user to upgrade.
    `schema_version` bumps when the CLI/server contract changes incompatibly.
    """

    cliff: str
    opencode: str
    schema_version: str = "1"
    min_cli: str = "0.1.0"


class SSEEvent(BaseModel):
    event: str = "message"
    data: str = ""
