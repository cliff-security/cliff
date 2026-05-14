"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from opensec.config import settings
from opensec.engine.client import opencode_client
from opensec.engine.models import HealthStatus
from opensec.engine.process import opencode_process

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def health(request: Request) -> HealthStatus:
    oc_healthy = await opencode_process.health_check()

    # Read model from OpenCode runtime (not the file, which can be stale).
    model = ""
    if oc_healthy:
        try:
            config = await opencode_client.get_config()
            model = config.get("model", "")
        except Exception:
            pass
    if not model:
        model = settings.opencode_model

    # ``ai_env_cache`` is the exact env dict the workspace process pool
    # injects into every per-workspace OpenCode subprocess. A non-empty
    # cache means a provider credential is present *and* resolved (vault
    # decrypt succeeded) — i.e. genuinely reachable by the subprocess.
    # ``ai_provider_credential_ok`` adds the last piece (Q01-B02): the
    # resolved credential was live-probed at boot / on connect and did not
    # come back as a definitive auth rejection. ``ai_provider_ready`` is
    # only True when both hold — a present-but-revoked key reads as not
    # ready, exactly as it behaves at agent-run time.
    ai_env_cache = getattr(request.app.state, "ai_env_cache", None) or {}
    credential_ok = getattr(
        request.app.state, "ai_provider_credential_ok", False
    )

    return HealthStatus(
        opensec="ok",
        opencode="ok" if oc_healthy else "unavailable",
        opencode_version=settings.opencode_version,
        model=model,
        ai_provider_ready=bool(ai_env_cache) and credential_ok,
    )
