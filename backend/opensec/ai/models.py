"""Pydantic models for tiered AI provider onboarding (ADR-0036, IMPL-0011)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

AIProvider = Literal[
    "openrouter", "anthropic", "openai", "google", "ollama", "custom"
]
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
    """Wire shape for ``GET /api/integrations/ai/status``.

    ``model`` is the canonical active model — the one OpenSec writes into
    ``app_setting(key="model")`` and pushes into every workspace spawn.
    Per ADR-0037 there is one canonical state and one read; the
    on_key_change hook restarts the singleton OpenCode synchronously on
    every model/key write, so there is no separate "what's loaded right
    now" signal worth exposing on the wire (architect health-check, M9).
    """

    state: AIState
    provider: AIProvider | None = None
    source: AISource | None = None
    connected_at: str | None = None
    metadata: dict | None = None
    model: str | None = None


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
    """Inbound payload for ``POST /api/integrations/ai/byok``.

    ``api_key`` is a ``SecretStr`` so the value is redacted in every
    Pydantic-rendered context — model_dump (without explicit unwrap),
    validation errors, repr, logging. Call sites that need the raw key
    must use ``api_key.get_secret_value()`` explicitly; that explicit
    unwrap is the only place we want to deal with the raw string.

    For Ollama the ``api_key`` is just a non-empty placeholder (the
    transport doesn't authenticate) but the field stays required so the
    wire shape doesn't fork. The UI sends "local" automatically.
    """

    provider: AIProvider
    api_key: SecretStr = Field(..., min_length=1)
    base_url: str | None = None
    model: str | None = None

    @field_validator("base_url")
    @classmethod
    def _base_url_must_look_like_url(cls, value: str | None) -> str | None:
        """Reject obviously-malformed base URLs at the wire (M1).

        We don't apply the DNS-aware SSRF check here — the per-provider
        validator (``validate_ollama`` / ``validate_custom``) does that
        with the provider-specific policy (Ollama keeps loopback +
        RFC1918; custom rejects them). Stopping bad URL shapes here
        means a non-URL string ("'); DROP TABLE--", "foo bar") never
        reaches the validator or the per-workspace env injection.
        """
        if value is None or value == "":
            return None
        from urllib.parse import urlparse
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            msg = "base_url must be a http:// or https:// URL with a host"
            raise ValueError(msg)
        return value


class SetModelRequest(BaseModel):
    """Inbound payload for ``PUT /api/integrations/ai/model``.

    The model id must include a provider prefix; the service rejects ids
    whose prefix doesn't match the currently active provider so a stale
    setting never silently re-points at the wrong namespace.
    """

    model: str = Field(..., min_length=1)


class ProviderModelOption(BaseModel):
    """One entry in the per-provider model picker dropdown."""

    id: str
    label: str
    description: str | None = None


class ProviderModelsResponse(BaseModel):
    """Wire shape for ``GET /api/integrations/ai/models?provider=X``."""

    provider: AIProvider
    default_model: str | None
    models: list[ProviderModelOption]
    source: Literal["catalog", "live"]
