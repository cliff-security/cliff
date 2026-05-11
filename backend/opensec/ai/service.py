"""AI integration service — the cross-vertical interface.

One place to read+write AI provider state. Encrypts the key via the existing
``CredentialVault`` (ADR-0016) — the GitHub App work uses the same pattern
(ADR-0035 / IMPL-0010). Workspace callers consume ``resolve_env_for_workspace``
to merge the right ``*_API_KEY`` into per-workspace OpenCode env vars.

Provider state lives in two tables that are kept in lockstep:

* ``integration_config`` — generic integration row (CASCADE owner for both
  ``credential`` and ``ai_integration``).
* ``ai_integration`` — AI-specific metadata (provider, source, etc.).

Plus the credential vault stores the encrypted ``api_key`` value namespaced
by ``(integration_id, "api_key")``.

The single-row-per-provider invariant from ADR-0036 is enforced at the DB
layer (unique index on ``provider``). Save methods clean up any prior row
for the same provider before creating the new one so a user can "reconnect"
without errors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opensec.ai import catalog
from opensec.ai import repo as ai_repo
from opensec.ai.models import (
    AIIntegration,
    AIProvider,
    AISource,
    AIStatus,
)
from opensec.db import repo_integration
from opensec.integrations.audit import AuditEvent
from opensec.models import IntegrationConfigCreate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import aiosqlite

    from opensec.integrations.audit import AuditLogger
    from opensec.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)


CREDENTIAL_KEY_NAME = "api_key"


class AIIntegrationService:
    """Atomic write boundary for AI provider state.

    The methods on this class are the only callers that touch raw API keys.
    Everything outside calls ``resolve_env_for_workspace`` (or reads
    ``AIStatus``), which never returns the raw key.
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        vault: CredentialVault,
        *,
        audit_logger: AuditLogger | None = None,
        on_key_change: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    ) -> None:
        """Construct the service.

        ``on_key_change`` (IMPL-0011 Phase F3) — optional async callable
        invoked after every save / disconnect with the new env-var dict
        (or ``{}`` after disconnect). Used by ``main.py`` lifespan to
        push fresh env into the singleton OpenCode process and restart
        it. Kept optional so unit tests don't need the engine wired up.
        """
        self._db = db
        self._vault = vault
        self._audit = audit_logger
        self._on_key_change = on_key_change

    # ------------------------------------------------------------------
    # Public reads
    # ------------------------------------------------------------------

    async def get_active(self) -> AIIntegration | None:
        return await ai_repo.get_active(self._db)

    async def get_status(self) -> AIStatus:
        record = await self.get_active()
        if record is None:
            return AIStatus(state="unconfigured")
        override = (
            catalog.resolve_model(record.provider)
            if catalog.has_override(record.provider)
            else None
        )
        return AIStatus(
            state="connected",
            provider=record.provider,
            source=record.source,
            connected_at=record.connected_at,
            metadata=record.metadata,
            override_model=override,
        )

    async def resolve_env_for_workspace(self) -> dict[str, str]:
        """Return the env-var dict to inject into a workspace OpenCode subprocess.

        Empty dict when unconfigured — the caller treats that as "no AI key
        injected" and the agent-button gate keeps the UI from launching
        agents anyway.
        """
        record = await self.get_active()
        if record is None:
            return {}
        try:
            raw_key = await self._vault.retrieve(
                record.integration_id, CREDENTIAL_KEY_NAME
            )
        except KeyError:
            logger.warning(
                "AI integration row exists but credential missing for provider %s",
                record.provider,
            )
            return {}
        env_var = catalog.env_var_name(record.provider)
        return {env_var: raw_key}

    # ------------------------------------------------------------------
    # Public writes
    # ------------------------------------------------------------------

    async def adopt_detected(
        self, provider: AIProvider, raw_key: str, source_path: str
    ) -> AIIntegration:
        """Persist an auto-detected key. Audit-logs the source path.

        Source path is recorded in both the ai_integration metadata
        (``metadata.source_path``) and the audit row (via
        ``parameters_hash``-style provider_name field for fast queries).
        """
        record = await self._save_internal(
            provider=provider,
            raw_key=raw_key,
            source="autodetect",
            metadata={"source_path": source_path},
        )
        await self._audit_log(
            event_type="ai_integration.adopt",
            provider=provider,
            integration_id=record.integration_id,
            verb=source_path,
        )
        await self._fire_key_change()
        return record

    async def save_byok(
        self,
        provider: AIProvider,
        raw_key: str,
        *,
        base_url: str | None = None,
    ) -> AIIntegration:
        """Persist a BYOK-supplied key. No validation here — caller validated."""
        metadata: dict | None = None
        if base_url:
            metadata = {"base_url": base_url}
        record = await self._save_internal(
            provider=provider,
            raw_key=raw_key,
            source="byok",
            metadata=metadata,
        )
        await self._audit_log(
            event_type="ai_integration.connect",
            provider=provider,
            integration_id=record.integration_id,
            verb="byok",
        )
        await self._fire_key_change()
        return record

    async def complete_oauth(
        self,
        provider: AIProvider,
        raw_key: str,
        metadata: dict | None = None,
    ) -> AIIntegration:
        """Persist a key delivered through OpenRouter OAuth."""
        record = await self._save_internal(
            provider=provider,
            raw_key=raw_key,
            source="openrouter-oauth",
            metadata=metadata,
        )
        await self._audit_log(
            event_type="ai_integration.connect",
            provider=provider,
            integration_id=record.integration_id,
            verb="openrouter-oauth",
        )
        await self._fire_key_change()
        return record

    async def disconnect(self) -> bool:
        """Delete the active row + cascade-clean its credential.

        Returns ``True`` if anything was removed; ``False`` if already empty
        (so HTTP callers can return 204 either way and stay idempotent).
        """
        record = await self.get_active()
        if record is None:
            return False

        # Deleting the integration_config row cascades to ai_integration and
        # credential. We rely on the DB-level cascade for atomicity.
        deleted = await repo_integration.delete_integration(
            self._db, record.integration_id
        )
        await self._audit_log(
            event_type="ai_integration.disconnect",
            provider=record.provider,
            integration_id=record.integration_id,
            verb=None,
        )
        await self._fire_key_change()
        return deleted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _save_internal(
        self,
        *,
        provider: AIProvider,
        raw_key: str,
        source: AISource,
        metadata: dict | None,
    ) -> AIIntegration:
        # If the same provider was previously connected, delete the prior
        # row (and its credential) so the unique-on-provider index stays
        # satisfied. Cascade does the work.
        existing = await ai_repo.get_by_provider(self._db, provider)
        if existing is not None:
            await repo_integration.delete_integration(
                self._db, existing.integration_id
            )

        # 1. Create the integration_config row that owns the FK + cascade.
        integration = await repo_integration.create_integration(
            self._db,
            IntegrationConfigCreate(
                adapter_type="ai_provider",
                provider_name=f"ai:{provider}",
                enabled=True,
                config=None,
                action_tier=0,
            ),
        )

        # 2. Encrypt the key into the vault.
        await self._vault.store(integration.id, CREDENTIAL_KEY_NAME, raw_key)

        # 3. Insert the ai_integration row.
        record = await ai_repo.create(
            self._db,
            integration_id=integration.id,
            provider=provider,
            source=source,
            metadata=metadata,
        )
        logger.info(
            "AI integration saved for provider %s via %s",
            provider,
            source,
        )
        return record

    async def _fire_key_change(self) -> None:
        """Call the on_key_change hook with the current env, if any.

        Never raises — singleton restart failures are non-fatal for the
        save path; the user can retry from the UI.
        """
        if self._on_key_change is None:
            return
        env = await self.resolve_env_for_workspace()
        try:
            await self._on_key_change(env)
        except Exception:  # noqa: BLE001
            logger.warning(
                "on_key_change hook raised; singleton may have stale env",
                exc_info=True,
            )

    async def _audit_log(
        self,
        *,
        event_type: str,
        provider: AIProvider,
        integration_id: str,
        verb: str | None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.log(
            AuditEvent(
                event_type=event_type,
                provider_name=f"ai:{provider}",
                integration_id=integration_id,
                verb=verb,
                action_tier=0,
                status="success",
            )
        )
