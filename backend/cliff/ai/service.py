"""AI integration service — the cross-vertical interface.

One place to read+write AI provider state. Encrypts the key via the existing
``CredentialVault`` (ADR-0016) — the GitHub App work uses the same pattern
(ADR-0035 / IMPL-0010). Workspace callers consume ``resolve_env_for_workspace``
to merge the right ``*_API_KEY`` (and, where applicable, ``*_BASE_URL``) into
the env the Pydantic AI model factory reads (ADR-0047).

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

**ADR-0037**: Active model is the canonical ``app_setting(key="model")`` row.
Every write path (BYOK, OAuth, autodetect) sets it atomically alongside the
provider; the dedicated :meth:`set_model` lets the UI picker change it
without re-saving the key. ``resolve_model_for_workspace`` reads the
canonical setting first and falls back to the catalog default only when
no setting exists or its prefix is stale.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cliff.ai import catalog, validators
from cliff.ai import repo as ai_repo
from cliff.ai.models import (
    AIIntegration,
    AIProvider,
    AISource,
    AIStatus,
    ValidationResult,
)
from cliff.db import repo_integration
from cliff.db.repo_setting import delete_setting, get_setting, upsert_setting
from cliff.integrations.audit import AuditEvent
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import aiosqlite

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)


CREDENTIAL_KEY_NAME = "api_key"
MODEL_SETTING_KEY = "model"


class ModelPrefixMismatchError(ValueError):
    """Raised when a model id's prefix doesn't match the active provider."""


class NoActiveProviderError(RuntimeError):
    """Raised when set_model is called without an active integration."""


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

        ``on_key_change`` (ADR-0037 / ADR-0047) — optional async callable
        invoked after every save / disconnect / model change with the new
        env-var dict (or ``{}`` after disconnect). Used by ``main.py``
        lifespan to refresh the warm env + model cache. Kept optional so
        unit tests don't need it wired up.
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
        """Compose the wire-shape status payload.

        Returns the canonical model (the value each agent run uses). Per
        ADR-0037 / ADR-0047 this is the **one** read: with the substrate
        in-process there's no separate engine config to probe, so a live
        probe + drift signal would add complexity without changing
        product behavior.
        """
        record = await self.get_active()
        if record is None:
            return AIStatus(state="unconfigured")
        canonical_model = await self._resolve_canonical_model(record.provider)
        return AIStatus(
            state="connected",
            provider=record.provider,
            source=record.source,
            connected_at=record.connected_at,
            metadata=record.metadata,
            model=canonical_model,
        )

    async def resolve_env_for_workspace(self) -> dict[str, str]:
        """Return the env-var dict the Pydantic AI model factory reads.

        Empty dict when unconfigured — the caller treats that as "no AI key
        resolved" and the agent-button gate keeps the UI from launching
        agents anyway.

        For providers that dispatch by base URL (``ollama``, ``custom``)
        the base URL is also included so the model factory targets the
        right host.
        Stored base URL (in ``ai_integration.metadata.base_url``) wins
        over the catalog's default.
        """
        record = await self.get_active()
        if record is None:
            return {}

        env: dict[str, str] = {}

        # API key (skip for keyless providers like Ollama).
        key_env_var = catalog.env_var_name(record.provider)
        if key_env_var is not None:
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
            # Empty credential → treat as unconfigured. A blank key would
            # still reach the provider and fail with an opaque 401, and
            # would flip the readiness gate to a falsely usable state.
            if not raw_key:
                logger.error(
                    "AI integration credential for provider %s decrypted to "
                    "an empty value — treating provider as unconfigured",
                    record.provider,
                )
                return {}
            env[key_env_var] = raw_key

        # Base URL: explicit ``base_url_env_var`` for providers that
        # dispatch by URL (Ollama, Custom); else the implicit
        # ``*_API_KEY → *_BASE_URL`` rename when the user pinned a proxy.
        # Stored value wins; catalog default fills in for base-URL-required
        # providers without a stored override.
        stored_base_url = (record.metadata or {}).get("base_url")
        explicit_base_url_env = catalog.base_url_env_var(record.provider)
        if explicit_base_url_env is not None:
            resolved = stored_base_url or catalog.default_base_url(
                record.provider
            )
            if resolved:
                env[explicit_base_url_env] = resolved
        elif stored_base_url and key_env_var is not None:
            env[key_env_var.replace("_API_KEY", "_BASE_URL")] = stored_base_url

        return env

    async def resolve_model_for_workspace(self) -> str | None:
        """Return the canonical active model id for workspace spawn.

        Reads ``app_setting(model)`` first (the value the UI picker
        writes); falls back to the catalog default for the active
        provider if no setting exists. Returns ``None`` when no provider
        is connected — caller treats that as "not configured."
        """
        record = await self.get_active()
        if record is None:
            return None
        return await self._resolve_canonical_model(record.provider)

    async def verify_active_credential(self) -> ValidationResult | None:
        """Live-probe the active provider's stored credential.

        Returns ``None`` when no provider is configured. Otherwise fires the
        same cheap auth probe the BYOK connect flow uses
        (:mod:`cliff.ai.validators`) and, on a clean pass, stamps
        ``last_validated_at`` on the integration row.

        This is the signal behind ``ai_provider_ready`` / ``cliffsec status``
        (Q01-B02): a credential that is *present and decrypts* is not the
        same as one that *authenticates* — a revoked or wrong key resolves
        into the workspace env just fine and only 401s at agent-run time.
        """
        record = await self.get_active()
        if record is None:
            return None
        metadata = record.metadata or {}

        # Ollama (no key) — just probe the runtime.
        if catalog.env_var_name(record.provider) is None:
            base_url = metadata.get("base_url") or catalog.default_base_url(
                record.provider
            )
            result = await validators.validate(
                record.provider, "local", base_url=base_url
            )
            if result.ok:
                await ai_repo.update_last_validated(
                    self._db, record.integration_id
                )
            return result

        try:
            raw_key = await self._vault.retrieve(
                record.integration_id, CREDENTIAL_KEY_NAME
            )
        except KeyError:
            return ValidationResult(
                ok=False,
                error_code="auth_failed",
                error_message="No stored credential for the active provider.",
            )
        if not raw_key:
            return ValidationResult(
                ok=False,
                error_code="auth_failed",
                error_message="Stored credential is empty.",
            )
        result = await validators.validate(
            record.provider,
            raw_key,
            base_url=metadata.get("base_url"),
            model=metadata.get("model"),
        )
        if result.ok:
            await ai_repo.update_last_validated(
                self._db, record.integration_id
            )
        return result

    # ------------------------------------------------------------------
    # Public writes — connect a provider
    # ------------------------------------------------------------------

    async def adopt_detected(
        self, provider: AIProvider, raw_key: str, source_path: str
    ) -> AIIntegration:
        """Persist an auto-detected key. Audit-logs the source path."""
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
        await self._sync_canonical_model(provider, None)
        await self._fire_key_change()
        return record

    async def save_byok(
        self,
        provider: AIProvider,
        raw_key: str,
        *,
        base_url: str | None = None,
        model: str | None = None,
    ) -> AIIntegration:
        """Persist a BYOK-supplied key. No validation here — caller validated.

        If *model* is supplied it becomes the canonical active model;
        otherwise the catalog default for *provider* is used. The
        canonical write is atomic with the provider/key write — they
        can never disagree on which provider's namespace the model id
        is in.
        """
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
        await self._sync_canonical_model(provider, model)
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
        await self._sync_canonical_model(provider, None)
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
    # Public writes — change the model
    # ------------------------------------------------------------------

    async def set_model(self, model_full_id: str) -> str:
        """Write *model_full_id* as the canonical active model.

        Rejects with :class:`ModelPrefixMismatchError` when the id's
        ``<provider>/...`` prefix doesn't match the currently active
        provider — that catches the "stored anthropic/... but switched to
        OpenRouter" footgun before workspace spawn tries to use it.

        Returns the model id that was persisted. Fires the key-change
        hook; workspaces pick the new model up at their next run via the
        model resolver (ADR-0047).
        """
        if "/" not in model_full_id:
            raise ModelPrefixMismatchError(
                f"Model id must be 'provider/model', got {model_full_id!r}."
            )
        record = await self.get_active()
        if record is None:
            raise NoActiveProviderError(
                "Cannot set a model without an active AI provider."
            )
        expected_prefix = record.provider
        actual_prefix = model_full_id.split("/", 1)[0]
        if actual_prefix != expected_prefix:
            raise ModelPrefixMismatchError(
                f"Model prefix {actual_prefix!r} does not match active "
                f"provider {expected_prefix!r}. Connect a different "
                f"provider first or pick a {expected_prefix}/* model."
            )
        await upsert_setting(
            self._db, MODEL_SETTING_KEY, {"full_id": model_full_id}
        )
        await self._fire_key_change()
        logger.info("AI model set to %s", model_full_id)
        return model_full_id

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _resolve_canonical_model(self, provider: AIProvider) -> str | None:
        """Read ``app_setting(model)`` if its prefix matches *provider*.

        Falls back to ``catalog.resolve_model(provider)`` (catalog default
        or env override) only when no canonical setting exists or its
        prefix is stale.
        """
        stored = await get_setting(self._db, MODEL_SETTING_KEY)
        if stored and isinstance(stored.value, dict):
            full_id = stored.value.get("full_id")
            if (
                isinstance(full_id, str)
                and full_id
                and full_id.startswith(f"{provider}/")
            ):
                return full_id
        return catalog.resolve_model(provider)

    async def _sync_canonical_model(
        self, provider: AIProvider, explicit_model: str | None
    ) -> None:
        """Write ``app_setting(model)`` to match the newly connected provider.

        Resolution priority:
          1. ``explicit_model`` (caller-supplied via BYOK form's model
             field, etc.) — only honored if its provider prefix matches.
          2. ``_resolve_canonical_model`` (existing setting if its
             prefix matches; else catalog default).
        Writes a row only if a non-empty model id resolves. For Ollama on
        a fresh connect with no explicit model and no prior setting, the
        canonical row is wiped — the picker will land on /api/tags and
        the user picks before spawning a workspace. (M12: this used to
        re-implement ``_resolve_canonical_model`` inline.)
        """
        if explicit_model:
            if "/" not in explicit_model:
                explicit_model = f"{provider}/{explicit_model}"
            elif not explicit_model.startswith(f"{provider}/"):
                logger.warning(
                    "Ignoring explicit model %s — prefix doesn't match provider %s",
                    explicit_model,
                    provider,
                )
                explicit_model = None

        chosen = explicit_model or await self._resolve_canonical_model(provider)

        if not chosen:
            # No default and no explicit pick (Ollama on fresh connect).
            # Remove any stale row so spawn-time resolution doesn't leak
            # the previous provider's model into the new context.
            await delete_setting(self._db, MODEL_SETTING_KEY)
            return

        await upsert_setting(self._db, MODEL_SETTING_KEY, {"full_id": chosen})

    async def _save_internal(
        self,
        *,
        provider: AIProvider,
        raw_key: str,
        source: AISource,
        metadata: dict | None,
    ) -> AIIntegration:
        # Enforce the single-active-row invariant by deleting whatever's
        # currently active before inserting. The unique index on
        # ``provider`` means a same-provider reconnect would otherwise
        # fail; cascade cleans the credential.
        existing = await self.get_active()
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

        # 2. Encrypt the key into the vault (Ollama uses a placeholder so
        #    disconnect's cascade-clean has a single shape to wipe).
        key_to_store = (
            raw_key if catalog.env_var_name(provider) is not None else "local"
        )
        await self._vault.store(integration.id, CREDENTIAL_KEY_NAME, key_to_store)

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

        Never raises — hook failures are non-fatal for the save path; the
        user can retry from the UI. The hook lets callers (e.g. app
        startup) refresh any cached env snapshot when the key changes.
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


__all__ = [
    "AIIntegrationService",
    "ModelPrefixMismatchError",
    "NoActiveProviderError",
    "CREDENTIAL_KEY_NAME",
    "MODEL_SETTING_KEY",
]
