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

from opensec.ai import autodetect, validators
from opensec.ai.models import (
    AIStatus,
    AutodetectResponse,
    BYOKRequest,
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
    return AIIntegrationService(db, vault, audit_logger=audit)


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
