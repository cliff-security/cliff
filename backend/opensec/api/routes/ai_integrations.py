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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from opensec.ai import autodetect, openrouter_oauth, validators
from opensec.ai.models import (
    AIStatus,
    AutodetectResponse,
    BYOKRequest,
    OpenRouterStartResponse,
    OpenRouterStatusResponse,
)
from opensec.ai.openrouter_oauth import (
    OAuthExchangeError,
    OAuthSession,
    Port3000UnavailableError,
)
from opensec.ai.service import AIIntegrationService
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
        except Exception as exc:  # noqa: BLE001 — surface any DB/vault failure as error
            s.status = "error"
            s.detail = f"Could not persist key: {exc}"
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
    validation = await validators.validate(
        body.provider,
        body.api_key,
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
    await service.save_byok(body.provider, body.api_key, base_url=body.base_url)
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
# Disconnect
# ---------------------------------------------------------------------------


class DisconnectResponse(BaseModel):
    status: str
    revoke_url: str


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
