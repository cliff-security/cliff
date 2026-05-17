"""One-shot migration: legacy ``app_setting:api_key:*`` → ``ai_integration``.

The legacy paste flow stored keys as JSON blobs under
``app_setting`` rows keyed ``api_key:<opencode-provider-id>``. The new
flow (ADR-0036) is the single source of truth.

This module runs once at startup. If the new ``ai_integration`` table
is empty AND at least one legacy ``api_key:*`` row exists, the most
recently-touched legacy entry is silently rehomed into the new path
via ``AIIntegrationService.save_byok``. Validation is intentionally
skipped — the key was already working in the legacy path, so we trust
it; if it stops working the user will hit it on the next agent run
and can re-paste through the unified flow.

The legacy ``app_setting`` row is left in place so the old code path
keeps working through a downgrade. A follow-up release will retire
the legacy endpoints entirely.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cliff.ai import repo as ai_repo
from cliff.db import repo_setting

if TYPE_CHECKING:
    import aiosqlite

    from cliff.ai.models import AIProvider
    from cliff.ai.service import AIIntegrationService

logger = logging.getLogger(__name__)


# Map legacy OpenCode provider IDs to the new AIProvider literal.
# Anything not in this set is silently skipped — the new model doesn't
# carry e.g. "google" (Gemini) yet; the user re-pastes via BYOK if they
# want to keep it.
_LEGACY_TO_AI_PROVIDER: dict[str, AIProvider] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openrouter": "openrouter",
}


async def migrate_legacy_api_keys_once(
    db: aiosqlite.Connection,
    service: AIIntegrationService,
) -> None:
    """Migrate the most recent legacy ``api_key:*`` row, if any.

    Idempotent: skips if the new table already has any rows. Best-
    effort: errors are logged and swallowed so a malformed legacy row
    can't block app boot.
    """
    try:
        existing = await ai_repo.get_active(db)
        if existing is not None:
            return

        legacy_rows = await repo_setting.list_settings(db, prefix="api_key:")
        if not legacy_rows:
            return

        # Pick the most recently updated row.
        legacy_rows.sort(key=lambda s: s.updated_at, reverse=True)
        for row in legacy_rows:
            provider_id = row.key.removeprefix("api_key:")
            ai_provider = _LEGACY_TO_AI_PROVIDER.get(provider_id)
            if ai_provider is None:
                continue
            value = row.value
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    continue
            if not isinstance(value, dict):
                continue
            raw_key = value.get("key")
            if not isinstance(raw_key, str) or not raw_key:
                continue
            await service.save_byok(ai_provider, raw_key)
            logger.info(
                "Migrated legacy AI key (%s) to ai_integration", ai_provider
            )
            return
    except Exception:
        logger.warning(
            "Legacy AI key migration failed (continuing without migration)",
            exc_info=True,
        )
