"""Settings API endpoints — model, API keys, integrations, registry, credentials."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from cliff.config import settings as app_settings
from cliff.db.connection import get_db
from cliff.db.repo_integration import (
    create_integration,
    delete_integration,
    get_integration,
    list_integrations,
    update_integration,
)
from cliff.engine.client import opencode_client
from cliff.engine.config_manager import config_manager
from cliff.integrations.audit import AuditEvent
from cliff.integrations.connection_tester import run_connection_test
from cliff.integrations.health import IntegrationHealthMonitor
from cliff.integrations.registry import (
    RegistryEntry,
    get_registry_entry,
    load_registry,
)
from cliff.integrations.vault import CredentialKeyError
from cliff.models import (
    ApiKeyCreate,
    CredentialCreate,
    CredentialInfo,
    IntegrationConfig,
    IntegrationConfigCreate,
    IntegrationConfigUpdate,
    IntegrationHealthStatus,
    ModelConfig,
    ModelUpdateRequest,
    TestConnectionResult,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import aiosqlite

router = APIRouter(tags=["settings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _emit_audit(request: Request, **kwargs) -> None:
    """Emit an audit event if the audit logger is available."""
    audit_logger = getattr(request.app.state, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(AuditEvent(**kwargs))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@router.get("/settings/model", response_model=ModelConfig)
async def get_model(request: Request, db=Depends(get_db)):
    """Return the canonical active model (ADR-0037).

    Thin shim over :class:`AIIntegrationService` so the CLI (``cliff
    model get``) and the new Settings UI agree byte-for-byte. Falls
    back to the old ``opencode.json``-derived value when no AI
    provider is connected so legacy users without an ``ai_integration``
    row still get something meaningful.
    """
    vault = getattr(request.app.state, "vault", None)
    if vault is not None:
        from cliff.ai.service import AIIntegrationService

        service = AIIntegrationService(db, vault)
        full_id = await service.resolve_model_for_workspace()
        if full_id:
            parts = full_id.split("/", 1)
            return ModelConfig(
                model_full_id=full_id,
                provider=parts[0] if len(parts) == 2 else "",
                model_id=parts[1] if len(parts) == 2 else full_id,
            )
    try:
        return await config_manager.get_model()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenCode unavailable: {exc}") from exc


@router.put("/settings/model", response_model=ModelConfig)
async def update_model(body: ModelUpdateRequest, request: Request, db=Depends(get_db)):
    """Persist a model change (ADR-0037).

    Routes through :class:`AIIntegrationService.set_model` when a
    provider is connected. On a fresh install with no provider yet,
    falls through to the legacy ``config_manager.update_model`` so
    ``cliffsec model set`` during install still works before BYOK.
    """
    vault = getattr(request.app.state, "vault", None)
    if vault is not None:
        from cliff.ai import repo as ai_repo
        from cliff.ai.service import (
            AIIntegrationService,
            ModelPrefixMismatchError,
        )

        active = await ai_repo.get_active(db)
        if active is not None:
            on_key_change = getattr(request.app.state, "ai_on_key_change", None)
            service = AIIntegrationService(
                db, vault, on_key_change=on_key_change
            )
            try:
                await service.set_model(body.model_full_id)
            except ModelPrefixMismatchError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            parts = body.model_full_id.split("/", 1)
            return ModelConfig(
                model_full_id=body.model_full_id,
                provider=parts[0] if len(parts) == 2 else "",
                model_id=parts[1] if len(parts) == 2 else body.model_full_id,
            )

    try:
        return await config_manager.update_model(db, body.model_full_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenCode unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@router.get("/settings/providers")
async def list_providers():
    try:
        return await config_manager.list_available_providers()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenCode unavailable: {exc}") from exc


@router.get("/settings/providers/configured")
async def get_configured_providers():
    try:
        providers = await config_manager.get_configured_providers()
        auth = await config_manager.get_auth_status()
        return {"providers": providers, "auth": auth}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenCode unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Provider probe (PRD-0004 Story 4 / ADR-0031)
# ---------------------------------------------------------------------------


class ProviderTestRequest(BaseModel):
    """Optional staged config. Alpha passes nothing and probes the currently
    configured provider/model/key; a future UI can preview unsaved staged
    config by populating these fields. Ignored today — probe uses whatever
    OpenCode has configured — but kept so the wire shape is stable.
    """

    provider: str | None = None
    model: str | None = None
    api_key: str | None = None


class ProviderTestResult(BaseModel):
    ok: bool
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None


# The probe sends a real "Say OK" through OpenCode and waits for the full
# assistant reply. The slowest realistic path is OpenRouter → small model
# (Haiku, Hy3) where queue + cold-start + inference + token streaming
# routinely lands at 10-20s on the first call. 30s gives the worst-case
# real run room to complete; the UI shows a "Testing…" spinner the whole
# time so the wait is visible.
_PROBE_TIMEOUT_SECONDS = 30.0
_PROBE_PROMPT = "Say OK"

_ERROR_COPY: dict[str, str] = {
    "auth_failed": "Authentication failed — check your API key",
    "model_not_found": "Model not found — check the model name spelling",
    "timeout": "Timed out — check network or try again",
    "rate_limited": "Rate limited — try again in a minute",
}


def _classify_http_error(status: int, body: str) -> str:
    lower = body.lower()
    if status in (401, 403):
        return "auth_failed"
    if status == 429:
        return "rate_limited"
    if status == 404:
        return "model_not_found"
    if "model" in lower and ("not found" in lower or "unsupported" in lower):
        return "model_not_found"
    if "unauthor" in lower or "invalid api key" in lower:
        return "auth_failed"
    if "rate limit" in lower:
        return "rate_limited"
    return "other"


def _error_message_for(code: str, body: str) -> str:
    return _ERROR_COPY.get(code, (body or "Probe failed").strip()[:200])


@router.post(
    "/settings/providers/test",
    response_model=ProviderTestResult,
)
async def test_provider(
    body: ProviderTestRequest | None = None,  # noqa: ARG001 — shape-stable
) -> ProviderTestResult:
    """End-to-end probe of the configured provider+model (ADR-0031).

    Sends a bounded ``"Say OK"`` chat call through OpenCode with a 30s
    timeout and classifies the outcome into
    ``{ok, latency_ms, error_code, error_message}``. Always returns HTTP
    200; ``ok`` reflects the probe result.
    """
    return await _probe_opencode(opencode_client)


async def _probe_opencode(client) -> ProviderTestResult:
    start = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    try:
        session = await client.create_session()
        response = await asyncio.wait_for(
            client.send_and_get_response(
                session.id,
                _PROBE_PROMPT,
                timeout=_PROBE_TIMEOUT_SECONDS,
            ),
            timeout=_PROBE_TIMEOUT_SECONDS + 1.0,
        )
    except TimeoutError:
        return ProviderTestResult(
            ok=False,
            latency_ms=int(_PROBE_TIMEOUT_SECONDS * 1000),
            error_code="timeout",
            error_message=_ERROR_COPY["timeout"],
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response is not None else ""
        status = exc.response.status_code if exc.response is not None else 0
        code = _classify_http_error(status, body)
        return ProviderTestResult(
            ok=False,
            latency_ms=_elapsed_ms(),
            error_code=code,
            error_message=_error_message_for(code, body),
        )
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
        return ProviderTestResult(
            ok=False,
            latency_ms=_elapsed_ms(),
            error_code="timeout",
            error_message=_error_message_for("timeout", str(exc)),
        )
    except Exception as exc:  # noqa: BLE001 — classify, don't leak
        return ProviderTestResult(
            ok=False,
            latency_ms=_elapsed_ms(),
            error_code="other",
            error_message=str(exc)[:200] or "Probe failed",
        )

    if not response:
        return ProviderTestResult(
            ok=False,
            latency_ms=_elapsed_ms(),
            error_code="timeout",
            error_message=_ERROR_COPY["timeout"],
        )
    return ProviderTestResult(ok=True, latency_ms=_elapsed_ms())


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


@router.get("/settings/api-keys")
async def list_api_keys(db=Depends(get_db)):
    return await config_manager.get_api_keys(db)


@router.put("/settings/api-keys/{provider}")
async def set_api_key(provider: str, body: ApiKeyCreate, db=Depends(get_db)):
    return await config_manager.set_api_key(db, provider, body.key)


@router.delete("/settings/api-keys/{provider}", status_code=204)
async def delete_api_key(provider: str, db=Depends(get_db)):
    deleted = await config_manager.delete_api_key(db, provider)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found")


# ---------------------------------------------------------------------------
# Integration registry
# ---------------------------------------------------------------------------


def _github_app_available() -> bool:
    """ADR-0035: True when the shared GitHub App + Device Flow onboarding
    surface is configured on this instance (env ``CLIFF_GITHUB_APP_CLIENT_ID``
    and ``CLIFF_GITHUB_APP_SLUG`` both non-empty)."""
    return bool(
        app_settings.github_app_client_id and app_settings.github_app_slug
    )


def _enrich_registry_entry(entry: RegistryEntry) -> RegistryEntry:
    """Set ``github_app_available`` on the github entry; pass others through."""
    if entry.id == "github":
        return entry.model_copy(update={"github_app_available": _github_app_available()})
    return entry


@router.get("/settings/integrations/registry", response_model=list[RegistryEntry])
async def list_registry():
    """List all available integrations from the builtin registry."""
    return [_enrich_registry_entry(e) for e in load_registry()]


@router.get("/settings/integrations/registry/{entry_id}", response_model=RegistryEntry)
async def get_registry_entry_endpoint(entry_id: str):
    """Get a single registry entry with full setup guide."""
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    return _enrich_registry_entry(entry)


# ---------------------------------------------------------------------------
# Integrations CRUD (with audit instrumentation)
# ---------------------------------------------------------------------------


@router.get("/settings/integrations", response_model=list[IntegrationConfig])
async def list_integrations_endpoint(db=Depends(get_db)):
    rows = await list_integrations(db)
    # Tag each github row with its auth_method + github_login so the
    # frontend can branch without polling /api/integrations/github/status
    # (race-free, ADR-0035) AND show "Connected as @<login>" without an
    # extra round-trip.
    cursor = await db.execute(
        "SELECT integration_id, github_login FROM github_app_installation"
    )
    app_flow_meta = {r["integration_id"]: r["github_login"] for r in await cursor.fetchall()}
    for row in rows:
        if row.provider_name.lower() == "github":
            if row.id in app_flow_meta:
                row.auth_method = "github_app"
                row.github_login = app_flow_meta[row.id]
            else:
                row.auth_method = "pat"
    return rows


@router.post("/settings/integrations", response_model=IntegrationConfig, status_code=201)
async def create_integration_endpoint(
    body: IntegrationConfigCreate, request: Request, db=Depends(get_db)
):
    result = await create_integration(db, body)
    await _emit_audit(
        request,
        event_type="integration.create",
        integration_id=result.id,
        provider_name=body.provider_name,
        status="success",
    )
    return result


@router.put("/settings/integrations/{integration_id}", response_model=IntegrationConfig)
async def update_integration_endpoint(
    integration_id: str, body: IntegrationConfigUpdate, request: Request, db=Depends(get_db)
):
    result = await update_integration(db, integration_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="Integration not found")
    await _emit_audit(
        request,
        event_type="integration.update",
        integration_id=integration_id,
        provider_name=result.provider_name,
        status="success",
    )
    return result


@router.delete("/settings/integrations/{integration_id}", status_code=204)
async def delete_integration_endpoint(
    integration_id: str, request: Request, db=Depends(get_db)
):
    # Cascade-delete credentials via vault if available.
    vault = getattr(request.app.state, "vault", None)
    if vault is not None:
        await vault.delete_for_integration(integration_id)

    deleted = await delete_integration(db, integration_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Integration not found")
    await _emit_audit(
        request,
        event_type="integration.delete",
        integration_id=integration_id,
        status="success",
    )


# ---------------------------------------------------------------------------
# Credentials (per integration)
# ---------------------------------------------------------------------------


def _get_vault(request: Request):
    """Get the vault from app.state or raise 503."""
    vault = getattr(request.app.state, "vault", None)
    if vault is None:
        raise HTTPException(
            status_code=503,
            detail="Credential vault not initialized. Set CLIFF_CREDENTIAL_KEY.",
        )
    return vault


@router.get(
    "/settings/integrations/{integration_id}/credentials",
    response_model=list[CredentialInfo],
)
async def list_credentials(
    integration_id: str, request: Request, db: aiosqlite.Connection = Depends(get_db)
):
    """List credential key names for an integration (no values)."""
    integration = await get_integration(db, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    vault = _get_vault(request)
    keys = await vault.list_keys(integration_id)
    return [CredentialInfo(**k) for k in keys]


@router.post(
    "/settings/integrations/{integration_id}/credentials",
    response_model=CredentialInfo,
    status_code=201,
)
async def store_credential(
    integration_id: str,
    body: CredentialCreate,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Store an encrypted credential for an integration."""
    integration = await get_integration(db, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    vault = _get_vault(request)
    try:
        await vault.store(integration_id, body.key_name, body.value)
    except CredentialKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await _emit_audit(
        request,
        event_type="credential.store",
        integration_id=integration_id,
        provider_name=integration.provider_name,
        status="success",
    )

    # Return info (no value).
    keys = await vault.list_keys(integration_id)
    for k in keys:
        if k["key_name"] == body.key_name:
            return CredentialInfo(**k)
    # Fallback (should not happen).
    return CredentialInfo(key_name=body.key_name, created_at="")


@router.delete(
    "/settings/integrations/{integration_id}/credentials/{key_name}",
    status_code=204,
)
async def delete_credential(
    integration_id: str, key_name: str, request: Request, db=Depends(get_db)
):
    """Delete a single credential."""
    vault = _get_vault(request)
    deleted = await vault.delete(integration_id, key_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    await _emit_audit(
        request,
        event_type="credential.delete",
        integration_id=integration_id,
        status="success",
    )


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@router.post(
    "/settings/integrations/{integration_id}/test",
    response_model=TestConnectionResult,
)
async def test_connection(
    integration_id: str, request: Request, db: aiosqlite.Connection = Depends(get_db)
):
    """Test an integration's credentials by verifying they can be decrypted."""
    integration = await get_integration(db, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    vault = _get_vault(request)

    try:
        creds = await vault.get_credentials_for_workspace(integration_id)
    except CredentialKeyError as exc:
        result = TestConnectionResult(success=False, message=f"Vault error: {exc}")
        await _emit_audit(
            request,
            event_type="integration.test",
            integration_id=integration_id,
            provider_name=integration.provider_name,
            status="error",
            error_message=str(exc),
        )
        return result

    if not creds:
        result = TestConnectionResult(
            success=False, message="No credentials configured for this integration."
        )
        await _emit_audit(
            request,
            event_type="integration.test",
            integration_id=integration_id,
            provider_name=integration.provider_name,
            status="error",
            error_message="No credentials",
        )
        return result

    # Dispatch to a real connection tester if one exists for this provider.
    registry_id = integration.provider_name.lower().replace(" ", "-")
    result = await run_connection_test(registry_id, creds)

    if result is None:
        # No tester registered — fall back to "credentials decrypted" check.
        result = TestConnectionResult(
            success=True,
            message=f"Credentials valid ({len(creds)} key(s) decrypted successfully).",
            details={"credential_keys": list(creds.keys())},
        )

    await _emit_audit(
        request,
        event_type="integration.test",
        integration_id=integration_id,
        provider_name=integration.provider_name,
        status="success" if result.success else "error",
        error_message=result.message if not result.success else None,
    )
    return result


# ---------------------------------------------------------------------------
# Integration health
# ---------------------------------------------------------------------------


def _get_health_monitor(request: Request) -> IntegrationHealthMonitor:
    """Build a health monitor from app.state components."""
    vault = _get_vault(request)
    audit_logger = getattr(request.app.state, "audit_logger", None)
    return IntegrationHealthMonitor(vault, audit_logger=audit_logger)


@router.get(
    "/settings/integrations/{integration_id}/health",
    response_model=IntegrationHealthStatus,
)
async def check_integration_health(
    integration_id: str,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Run a health check for a single integration."""
    monitor = _get_health_monitor(request)
    health = await monitor.check_health(db, integration_id)
    if health is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return health


@router.get(
    "/settings/integrations/health",
    response_model=list[IntegrationHealthStatus],
)
async def check_all_integrations_health(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Run health checks for all enabled integrations."""
    monitor = _get_health_monitor(request)
    return await monitor.check_all(db)
