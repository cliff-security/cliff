"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cliff.models import HealthStatus, substrate_version

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def health(request: Request) -> HealthStatus:
    # The agent substrate runs in-process via Pydantic AI — there's no
    # subprocess to probe, so "opencode" is always "ok" when the app is up.
    # The field shape is kept for backward compatibility (frontend health
    # card + cliffsec status); see HealthStatus.

    # ``ai_model_cache`` is the canonical active model resolved at boot / on
    # provider change (ADR-0047); empty string when no provider is connected.
    model = getattr(request.app.state, "ai_model_cache", None)

    # ``ai_env_cache`` is the resolved provider env. A non-empty cache means a
    # provider credential is present *and* resolved (vault decrypt succeeded);
    # ``ai_provider_credential_ok`` adds that it was live-probed and not a
    # definitive auth rejection. ``ai_provider_ready`` requires both.
    ai_env_cache = getattr(request.app.state, "ai_env_cache", None) or {}
    credential_ok = getattr(request.app.state, "ai_provider_credential_ok", False)

    return HealthStatus(
        cliff="ok",
        opencode="ok",
        opencode_version=substrate_version(),
        model=model or "",
        ai_provider_ready=bool(ai_env_cache) and credential_ok,
    )
