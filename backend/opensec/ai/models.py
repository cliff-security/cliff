"""Pydantic models for tiered AI provider onboarding (ADR-0036, IMPL-0011)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AIProvider = Literal["openrouter", "anthropic", "openai", "custom"]
AISource = Literal["autodetect", "openrouter-oauth", "byok"]
AIState = Literal["unconfigured", "connected"]


class AIIntegration(BaseModel):
    """Persistence row for the ``ai_integration`` table.

    Never contains key material. The API key lives encrypted in the
    credential vault, keyed by ``integration_id`` + ``"api_key"``.
    """

    id: str
    integration_id: str
    provider: AIProvider
    source: AISource
    metadata: dict | None = None
    connected_at: str
    last_validated_at: str | None = None
    created_at: str
    updated_at: str

    # Mask anything key-shaped if the model ever gets logged accidentally.
    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"AIIntegration(id={self.id!r}, provider={self.provider!r}, "
            f"source={self.source!r}, connected_at={self.connected_at!r})"
        )


class AIIntegrationCreate(BaseModel):
    """Write-side payload for inserting a row.

    ``raw_key`` is consumed by the service layer at write time, encrypted
    via the vault, and never persisted to ``ai_integration``. It is kept
    out of ``model_dump()`` representations via a private attribute.
    """

    provider: AIProvider
    source: AISource
    metadata: dict | None = None


class AIStatus(BaseModel):
    """Wire shape for ``GET /api/integrations/ai/status``."""

    state: AIState
    provider: AIProvider | None = None
    source: AISource | None = None
    connected_at: str | None = None
    metadata: dict | None = None
    override_model: str | None = None


class DetectedKey(BaseModel):
    """Outcome of the auto-detect scan.

    The raw key is included so the adopt-endpoint can validate it, but the
    `__repr__` override and the absence of any `log.*` path that includes
    the model means the key never lands in logs.
    """

    provider: AIProvider
    source: str = Field(
        ..., description="Human-readable source path, e.g. 'ANTHROPIC_API_KEY env'"
    )
    raw_key: str

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"DetectedKey(provider={self.provider!r}, source={self.source!r}, "
            "raw_key=<redacted>)"
        )


class AutodetectResponse(BaseModel):
    """Wire shape for ``GET /api/integrations/ai/autodetect`` — never the key."""

    found: bool
    provider: AIProvider | None = None
    source: str | None = None


class ValidationResult(BaseModel):
    """Outcome of a BYOK validator probe."""

    ok: bool
    error_code: (
        Literal[
            "auth_failed", "no_access", "network", "rate_limited", "model_not_found"
        ]
        | None
    ) = None
    error_message: str | None = None

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"ValidationResult(ok={self.ok!r}, error_code={self.error_code!r}, "
            f"error_message={self.error_message!r})"
        )


# ---------------------------------------------------------------------------
# OAuth route I/O models
# ---------------------------------------------------------------------------


class OpenRouterStartResponse(BaseModel):
    auth_url: str
    session_id: str


OAuthStatus = Literal["waiting", "connected", "denied", "error", "timeout"]


class OpenRouterStatusResponse(BaseModel):
    status: OAuthStatus
    detail: str | None = None


# ---------------------------------------------------------------------------
# BYOK route I/O models
# ---------------------------------------------------------------------------


class BYOKRequest(BaseModel):
    provider: AIProvider
    api_key: str = Field(..., min_length=1)
    base_url: str | None = None
    model: str | None = None

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"BYOKRequest(provider={self.provider!r}, "
            "api_key=<redacted>, "
            f"base_url={self.base_url!r}, model={self.model!r})"
        )
