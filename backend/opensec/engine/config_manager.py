"""Orchestrates config changes between OpenCode API, DB, and opencode.json."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opensec.config import settings
from opensec.db.repo_setting import delete_setting, get_setting, list_settings, upsert_setting
from opensec.engine.client import opencode_client

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


def mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if len(key) <= 8:
        return "****"
    return key[:3] + "..." + key[-4:]


class ConfigManager:
    """Coordinates config changes between OpenCode API, DB, and opencode.json."""

    # --- Model ---

    async def get_model(self) -> dict:
        """Get current model from OpenCode's /config endpoint."""
        try:
            config = await opencode_client.get_config()
            model_full_id = config.get("model", "")
        except Exception:
            model_full_id = settings.opencode_model

        parts = model_full_id.split("/", 1) if model_full_id else ["", ""]
        return {
            "model_full_id": model_full_id,
            "provider": parts[0] if len(parts) == 2 else "",
            "model_id": parts[1] if len(parts) == 2 else model_full_id,
        }

    async def update_model(self, db: aiosqlite.Connection, model_full_id: str) -> dict:
        """Change model via PUT /config. Also persist to DB and opencode.json."""
        if "/" not in model_full_id:
            raise ValueError(
                f"Model must be in 'provider/model-id' format, got: {model_full_id}"
            )

        # 1. Update OpenCode at runtime — instant effect
        await opencode_client.update_config({"model": model_full_id})

        # 2. Persist to opencode.json for restarts
        settings.write_opencode_config(model_full_id)

        # 3. Save to DB for reference
        await upsert_setting(db, "model", {"full_id": model_full_id})

        logger.info("Model updated to %s", model_full_id)
        return await self.get_model()

    # --- Providers ---

    async def list_available_providers(self) -> list[dict]:
        """GET /provider — full catalog of providers and models."""
        data = await opencode_client.list_providers()
        return data.get("all", [])

    async def get_configured_providers(self) -> dict:
        """GET /config/providers — configured providers with defaults."""
        return await opencode_client.get_configured_providers()

    async def get_auth_status(self) -> dict:
        """GET /provider/auth — which providers have credentials."""
        return await opencode_client.get_provider_auth()

    # --- API Keys ---

    async def set_api_key(
        self, db: aiosqlite.Connection, provider_id: str, key: str
    ) -> dict:
        """Set API key via PUT /auth/{id}. Also persist to DB.

        Persists to DB first (always works), then pushes to OpenCode as
        best-effort. If OpenCode rejects the provider (e.g. unknown provider
        name), the key is still saved and will be restored on next startup
        when the provider may be configured.
        """
        # 1. Persist to DB first — this always succeeds
        masked = mask_key(key)
        await upsert_setting(db, f"api_key:{provider_id}", {
            "key": key,
            "key_masked": masked,
        })

        # 2. Push to OpenCode at runtime — best-effort
        try:
            await opencode_client.set_auth(provider_id, {"type": "api", "key": key})
        except Exception:
            logger.warning(
                "Could not push API key to OpenCode for provider %s "
                "(key is saved and will be restored on restart)",
                provider_id,
            )

        logger.info("API key set for provider %s", provider_id)
        return {"provider": provider_id, "key_masked": masked, "has_credentials": True}

    async def get_api_keys(self, db: aiosqlite.Connection) -> list[dict]:
        """List API keys: DB-stored entries plus env-sourced ones discovered by OpenCode.

        DB rows always win on dedup — the user explicitly stored them, so they
        should override an env value of the same provider.
        """
        stored = await list_settings(db, prefix="api_key:")
        try:
            auth_status = await self.get_auth_status()
        except Exception:
            auth_status = {}

        results: list[dict] = []
        db_providers: set[str] = set()
        for setting in stored:
            provider_id = setting.key.removeprefix("api_key:")
            db_providers.add(provider_id)
            value = setting.value or {}
            provider_auth = auth_status.get(provider_id, [])
            results.append({
                "provider": provider_id,
                "key_masked": value.get("key_masked", "****"),
                "has_credentials": len(provider_auth) > 0,
                "source": "db",
                "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
            })

        for provider_id, auth_entries in auth_status.items():
            if provider_id in db_providers or not auth_entries:
                continue
            results.append({
                "provider": provider_id,
                "key_masked": None,
                "has_credentials": True,
                "source": "env",
                "updated_at": None,
            })

        return results

    async def delete_api_key(self, db: aiosqlite.Connection, provider_id: str) -> bool:
        """Remove stored key from DB."""
        return await delete_setting(db, f"api_key:{provider_id}")

    async def restore_keys_to_engine(self, db: aiosqlite.Connection) -> None:
        """On app startup, re-inject stored keys to OpenCode via /auth/{id}."""
        stored = await list_settings(db, prefix="api_key:")
        for setting in stored:
            provider_id = setting.key.removeprefix("api_key:")
            value = setting.value or {}
            key = value.get("key")
            if not key:
                continue
            try:
                await opencode_client.set_auth(provider_id, {"type": "api", "key": key})
                logger.info("Restored API key for provider %s", provider_id)
            except Exception:
                logger.warning("Failed to restore API key for provider %s", provider_id)

    # Also restore model from DB if opencode.json diverged
    async def reconcile_model(self, db: aiosqlite.Connection) -> None:
        """On startup, ensure opencode.json matches what's stored in DB."""
        stored = await get_setting(db, "model")
        if not stored or not stored.value:
            return
        stored_model = stored.value.get("full_id", "")
        current_model = settings.opencode_model
        if stored_model and stored_model != current_model:
            logger.info(
                "Reconciling model: DB has %s, opencode.json has %s",
                stored_model, current_model,
            )
            settings.write_opencode_config(stored_model)


# Singleton
config_manager = ConfigManager()
