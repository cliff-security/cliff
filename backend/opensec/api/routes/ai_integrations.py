"""Tiered AI provider onboarding routes (ADR-0036, IMPL-0011).

Mounted at ``/api/integrations/ai``. Endpoints:

- ``GET    /autodetect``           — silent scan, never returns key.
- ``POST   /autodetect/adopt``     — validate + persist a detected key.
- ``POST   /openrouter/start``     — kick off OAuth PKCE (Phase C).
- ``GET    /openrouter/status``    — frontend polls this every 1s.
- ``POST   /byok``                 — validate + persist a direct BYOK key.
- ``GET    /status``               — current AIStatus.
- ``POST   /disconnect``           — clear active integration.

The routes are stateless apart from the in-memory OAuth session store
(see ``openrouter_oauth.py``). All key material flows through the
``AIIntegrationService`` boundary — no other route sees raw keys.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from opensec.ai import autodetect, catalog, openrouter_oauth, validators
from opensec.ai.models import (
    AIProvider,
    AIStatus,
    AutodetectResponse,
    BYOKRequest,
    OpenRouterStartResponse,
    OpenRouterStatusResponse,
    ProviderModelOption,
    ProviderModelsResponse,
    SetModelRequest,
)
from opensec.ai.openrouter_oauth import (
    OAuthExchangeError,
    OAuthSession,
    Port3000UnavailableError,
)
from opensec.ai.service import (
    AIIntegrationService,
    ModelPrefixMismatchError,
    NoActiveProviderError,
)
from opensec.db.connection import get_db

if TYPE_CHECKING:
    import aiosqlite

    from opensec.integrations.audit import AuditLogger
    from opensec.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/ai", tags=["ai-integrations"])


# ---------------------------------------------------------------------------
# Service construction
# ---------------------------------------------------------------------------


def _get_service(request: Request, db: aiosqlite.Connection) -> AIIntegrationService:
    vault: CredentialVault | None = getattr(request.app.state, "vault", None)
    audit: AuditLogger | None = getattr(request.app.state, "audit_logger", None)
    if vault is None:
        raise HTTPException(
            status_code=503,
            detail="Credential vault not initialized.",
        )
    # IMPL-0011 Phase F3: singleton OpenCode restart hook. Wired on
    # app.state in main.py lifespan so every per-request service shares
    # the same engine handle.
    on_key_change = getattr(request.app.state, "ai_on_key_change", None)
    return AIIntegrationService(
        db, vault, audit_logger=audit, on_key_change=on_key_change
    )


# ---------------------------------------------------------------------------
# Auto-detect (Tier 1)
# ---------------------------------------------------------------------------


@router.get("/autodetect", response_model=AutodetectResponse)
async def autodetect_scan() -> AutodetectResponse:
    """Scan common locations for existing AI keys. Never returns the key."""
    detected = autodetect.scan()
    if detected is None:
        return AutodetectResponse(found=False)
    return AutodetectResponse(
        found=True, provider=detected.provider, source=detected.source
    )


@router.post("/autodetect/adopt", response_model=AIStatus)
async def autodetect_adopt(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> AIStatus:
    """Re-scan, validate, and persist a detected key.

    Re-running the scan inside the handler (rather than trusting the
    earlier GET) keeps adoption coherent if the user changed their env
    between clicks.
    """
    detected = autodetect.scan()
    if detected is None:
        raise HTTPException(status_code=404, detail="No detectable AI key found.")

    validation = await validators.validate(detected.provider, detected.raw_key)
    if not validation.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": validation.error_code,
                "error_message": validation.error_message,
            },
        )

    service = _get_service(request, db)
    await service.adopt_detected(detected.provider, detected.raw_key, detected.source)
    return await service.get_status()


# ---------------------------------------------------------------------------
# OpenRouter OAuth (Tier 2)
# ---------------------------------------------------------------------------


@router.post("/openrouter/start", response_model=OpenRouterStartResponse)
async def openrouter_start(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> OpenRouterStartResponse:
    """Begin an OAuth PKCE handshake.

    Mints a session, starts a one-shot listener on port 3000, returns the
    auth URL the frontend should open in a new tab.
    """
    store = openrouter_oauth.get_store()
    session, challenge = store.create()

    service = _get_service(request, db)

    async def _on_callback(s: OAuthSession, code: str, _state: str) -> None:
        try:
            data = await openrouter_oauth.exchange_code(code, s.verifier)
        except OAuthExchangeError as exc:
            s.status = "error"
            s.detail = str(exc)
            return
        api_key = data["key"]
        metadata: dict = {}
        for field in ("user_id", "user_email", "label"):
            if field in data and data[field]:
                metadata[field] = data[field]
        try:
            await service.complete_oauth(
                "openrouter", api_key, metadata=metadata or None
            )
        except Exception:  # noqa: BLE001 — log internally; the UI sees a fixed string
            logger.exception(
                "Could not persist OpenRouter key after OAuth exchange"
            )
            s.status = "error"
            s.detail = "Could not save the key. Try again or use BYOK."
            return
        s.status = "connected"
        s.result_metadata = metadata
        # Wipe the raw key from session memory.
        s.result_key = None

    try:
        await openrouter_oauth.start_listener(session, on_callback=_on_callback)
    except Port3000UnavailableError as exc:
        store.remove(session.session_id)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "port_3000_in_use",
                "message": (
                    "Port 3000 is needed for a secure handshake with OpenRouter. "
                    "Close the app using port 3000 and try again, or set up your "
                    "own API key instead."
                ),
            },
        ) from exc

    auth_url = openrouter_oauth.build_auth_url(challenge, session.state)
    return OpenRouterStartResponse(auth_url=auth_url, session_id=session.session_id)


@router.get("/openrouter/status", response_model=OpenRouterStatusResponse)
async def openrouter_status(session_id: str) -> OpenRouterStatusResponse:
    """Frontend polls this every ~1s while a session is in flight."""
    store = openrouter_oauth.get_store()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session_id.")

    # Once we've gone terminal we can free the listener.
    if session.is_terminal:
        await openrouter_oauth.stop_listener(session)

    return OpenRouterStatusResponse(status=session.status, detail=session.detail)


# ---------------------------------------------------------------------------
# BYOK (Tier 3)
# ---------------------------------------------------------------------------


@router.post("/byok", response_model=AIStatus)
async def byok(
    body: BYOKRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> AIStatus:
    """Validate + persist a directly-pasted API key."""
    raw_key = body.api_key.get_secret_value()
    validation = await validators.validate(
        body.provider,
        raw_key,
        base_url=body.base_url,
        model=body.model,
    )
    if not validation.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": validation.error_code,
                "error_message": validation.error_message,
            },
        )

    service = _get_service(request, db)
    await service.save_byok(
        body.provider,
        raw_key,
        base_url=body.base_url,
        model=body.model,
    )
    return await service.get_status()


# ---------------------------------------------------------------------------
# Status (read-only)
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AIStatus)
async def status(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> AIStatus:
    service = _get_service(request, db)
    return await service.get_status()


# ---------------------------------------------------------------------------
# Model picker (ADR-0037)
# ---------------------------------------------------------------------------


@router.put("/model", response_model=AIStatus)
async def set_active_model(
    body: SetModelRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> AIStatus:
    """Change the canonical active model.

    Validates that the model id's provider prefix matches the active
    integration. Workspace spawns pick up the new model immediately
    via the model resolver; the singleton restarts so chat sessions
    re-init against the new model on next request.
    """
    service = _get_service(request, db)
    try:
        await service.set_model(body.model)
    except NoActiveProviderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelPrefixMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await service.get_status()


# Suggested model lists per provider. Static for cloud providers (the live
# catalog from OpenCode is huge and noisy for the picker); the Ollama tile
# proxies /api/tags so the picker reflects what's actually installed on the
# host machine.
_SUGGESTED_MODELS: dict[AIProvider, list[ProviderModelOption]] = {
    # OpenRouter uses dots between version components in Anthropic slugs
    # (``claude-haiku-4.5``), not dashes. Picking from this list MUST yield
    # an id that OpenRouter actually accepts — a wrong slug surfaces only
    # at agent-run time when the session 500s with no assistant reply.
    "openrouter": [
        ProviderModelOption(
            id="openrouter/tencent/hy3-preview",
            label="Tencent Hy3 (preview)",
            description="262K context, $0.07 / $0.26 per 1M tokens — default.",
        ),
        ProviderModelOption(
            id="openrouter/anthropic/claude-haiku-4.5",
            label="Claude Haiku 4.5",
            description="Anthropic via OpenRouter — fast, cheap, broad coverage.",
        ),
        ProviderModelOption(
            id="openrouter/anthropic/claude-sonnet-4.5",
            label="Claude Sonnet 4.5",
            description="Anthropic's current flagship for security reasoning.",
        ),
        ProviderModelOption(
            id="openrouter/openai/gpt-5",
            label="GPT-5",
            description="OpenAI's flagship via OpenRouter.",
        ),
        ProviderModelOption(
            id="openrouter/google/gemini-2.5-flash",
            label="Gemini 2.5 Flash",
            description="Google's cheap workhorse via OpenRouter.",
        ),
        ProviderModelOption(
            id="openrouter/deepseek/deepseek-chat",
            label="DeepSeek Chat",
            description="Strong open-weight model at very low cost.",
        ),
    ],
    "anthropic": [
        ProviderModelOption(
            id="anthropic/claude-haiku-4-5",
            label="Claude Haiku 4.5",
            description="Default — cheapest current-generation Claude.",
        ),
        ProviderModelOption(
            id="anthropic/claude-sonnet-4-6",
            label="Claude Sonnet 4.6",
            description="Best security reasoning. ~5× cost of Haiku.",
        ),
        ProviderModelOption(
            id="anthropic/claude-opus-4-1",
            label="Claude Opus 4.1",
            description="Highest quality, highest cost.",
        ),
    ],
    "openai": [
        ProviderModelOption(
            id="openai/gpt-5",
            label="GPT-5",
            description="Default flagship.",
        ),
        ProviderModelOption(
            id="openai/gpt-5-mini",
            label="GPT-5 Mini",
            description="Smaller, cheaper variant.",
        ),
        ProviderModelOption(
            id="openai/gpt-4.1-mini",
            label="GPT-4.1 Mini",
            description="Solid all-rounder.",
        ),
    ],
    "google": [
        ProviderModelOption(
            id="google/gemini-2.5-flash",
            label="Gemini 2.5 Flash",
            description="Default — fast and on the AI Studio free tier.",
        ),
        ProviderModelOption(
            id="google/gemini-2.5-pro",
            label="Gemini 2.5 Pro",
            description="Higher quality, paid tier.",
        ),
    ],
    "ollama": [],
    "custom": [],
}


@router.get("/models", response_model=ProviderModelsResponse)
async def list_provider_models(
    provider: AIProvider,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> ProviderModelsResponse:
    """Return the model picker options for *provider*.

    For Ollama this hits ``{base_url}/api/tags`` so the picker reflects
    what the user has actually pulled. The base URL comes from the
    active integration's stored metadata if it matches *provider*,
    else the catalog default (``http://localhost:11434``).
    """
    default_model = catalog.resolve_model(provider)
    if provider == "ollama":
        base_url = catalog.default_base_url("ollama") or "http://localhost:11434"
        service = _get_service(request, db)
        record = await service.get_active()
        if record is not None and record.provider == "ollama":
            stored = (record.metadata or {}).get("base_url")
            if isinstance(stored, str) and stored:
                base_url = stored
        live = await _ollama_tags(base_url)
        return ProviderModelsResponse(
            provider=provider,
            default_model=default_model,
            models=live,
            source="live",
        )
    return ProviderModelsResponse(
        provider=provider,
        default_model=default_model,
        models=list(_SUGGESTED_MODELS.get(provider, [])),
        source="catalog",
    )


# Shared httpx client for Ollama /api/tags probes. Lazily constructed so
# imports don't try to create a client without a running event loop.
_ollama_client: httpx.AsyncClient | None = None


def _get_ollama_client() -> httpx.AsyncClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = httpx.AsyncClient(timeout=4.0)
    return _ollama_client


async def _ollama_tags(base_url: str) -> list[ProviderModelOption]:
    """Probe Ollama's /api/tags and convert to picker options."""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        resp = await _get_ollama_client().get(url)
    except httpx.HTTPError:
        return []
    if resp.status_code >= 300:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    tags = data.get("models") if isinstance(data, dict) else None
    if not isinstance(tags, list):
        return []
    options: list[ProviderModelOption] = []
    for entry in tags:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not isinstance(name, str) or not name:
            continue
        options.append(
            ProviderModelOption(
                id=f"ollama/{name}",
                label=name,
                description=_format_ollama_size(entry.get("size")),
            )
        )
    return options


def _format_ollama_size(size_bytes: object) -> str | None:
    if not isinstance(size_bytes, (int, float)):
        return None
    gb = size_bytes / 1_000_000_000
    if gb < 0.1:
        return None
    return f"{gb:.1f} GB"


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


@router.post("/disconnect")
async def disconnect(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> Response:
    """Clear the active AI integration locally.

    Idempotent: returns 204 whether or not there was anything to clear.
    Surface-area note: revoking OpenRouter keys server-side would require
    OpenRouter's client_secret, which we deliberately don't ship in the
    self-hosted code path (ADR-0036). The frontend surfaces the
    openrouter.ai/settings/keys link separately.
    """
    service = _get_service(request, db)
    await service.disconnect()
    return Response(status_code=204)
