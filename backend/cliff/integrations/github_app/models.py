"""Pydantic models for the GitHub App device flow (ADR-0035, IMPL-0010)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Polling state machine — ``installation_pending`` and ``device_pending``
# are non-terminal; the rest are terminal.
GithubAppPollingStatus = Literal[
    "installation_pending",
    "device_pending",
    "connected",
    "expired",
    "denied",
    "rate_limited",
    "error",
]

TERMINAL_POLLING_STATUSES: frozenset[str] = frozenset(
    {"connected", "expired", "denied", "error"}
)


class GithubAppInstallationCreate(BaseModel):
    """Payload for inserting a fresh in-flight install row."""

    integration_id: str
    app_slug: str
    client_id: str
    csrf_state: str
    user_code: str
    verification_uri: str
    device_code_expires_at: str  # ISO 8601
    polling_interval_seconds: int


class GithubAppInstallation(BaseModel):
    """Persistence row for the github_app_installation table."""

    id: str
    integration_id: str
    app_slug: str
    client_id: str
    installation_id: int | None = None
    installation_completed_at: str | None = None
    csrf_state: str
    user_code: str | None = None
    verification_uri: str | None = None
    device_code_expires_at: str | None = None
    polling_interval_seconds: int | None = None
    polling_status: GithubAppPollingStatus = "installation_pending"
    polling_error: str | None = None
    last_polled_at: str | None = None
    token_expires_at: str | None = None
    github_login: str | None = None
    last_validated_at: str | None = None
    connected_at: str | None = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Route I/O models (Phase 4 — kept here for cohesion)
# ---------------------------------------------------------------------------


class DeviceFlowConnectResponse(BaseModel):
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    install_url: str


class DeviceFlowStatusResponse(BaseModel):
    status: GithubAppPollingStatus
    user_code: str | None = None
    expires_at: str | None = None
    installation_id: int | None = None
    github_login: str | None = None
    error: str | None = None


class DeviceFlowDisconnectResponse(BaseModel):
    status: Literal["disconnected"] = "disconnected"
    manual_revoke_url: str
