"""Integration health monitoring (Phase I-2).

Checks whether stored credentials can be decrypted and whether the external
service is reachable.  Combines the vault and connection tester layers into
a single health status per integration.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.db.repo_integration import get_integration, list_integrations
from cliff.integrations.audit import AuditEvent
from cliff.integrations.connection_tester import run_connection_test
from cliff.models import IntegrationHealthStatus

if TYPE_CHECKING:
    import aiosqlite

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)


class IntegrationHealthMonitor:
    """Checks credential and connectivity health for integrations."""

    def __init__(
        self,
        vault: CredentialVault,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._vault = vault
        self._audit = audit_logger

    async def check_health(
        self,
        db: aiosqlite.Connection,
        integration_id: str,
    ) -> IntegrationHealthStatus | None:
        """Run a health check for a single integration.

        Returns ``None`` if the integration does not exist.
        """
        integration = await get_integration(db, integration_id)
        if integration is None:
            return None

        registry_id = integration.provider_name.lower().replace(" ", "-")
        now = datetime.now(UTC).isoformat()

        # 1. Check credentials.
        cred_status = "ok"
        creds: dict[str, str] = {}
        error_msg: str | None = None

        try:
            creds = await self._vault.get_credentials_for_workspace(integration_id)
            if not creds:
                cred_status = "missing"
                error_msg = "No credentials stored"
        except Exception as exc:
            cred_status = "decrypt_error"
            error_msg = f"Credential decryption failed: {type(exc).__name__}"

        # 2. Check connection (only if credentials are OK).
        conn_status = "unchecked"
        if cred_status == "ok":
            result = await run_connection_test(registry_id, creds)
            if result is None:
                conn_status = "unchecked"  # No tester for this provider.
            elif result.success:
                conn_status = "ok"
            else:
                conn_status = "error"
                error_msg = result.message

        # 3. Audit.
        if self._audit is not None:
            healthy = cred_status == "ok" and conn_status in ("ok", "unchecked")
            status = "success" if healthy else "error"
            await self._audit.log(
                AuditEvent(
                    event_type="integration.health_check",
                    integration_id=integration_id,
                    provider_name=integration.provider_name,
                    status=status,
                    error_message=error_msg,
                )
            )

        return IntegrationHealthStatus(
            integration_id=integration_id,
            registry_id=registry_id,
            provider_name=integration.provider_name,
            credential_status=cred_status,
            connection_status=conn_status,
            last_checked=now,
            error_message=error_msg,
        )

    async def check_all(
        self, db: aiosqlite.Connection
    ) -> list[IntegrationHealthStatus]:
        """Run health checks for all enabled integrations."""
        integrations = await list_integrations(db)
        results = []
        for integration in integrations:
            if not integration.enabled:
                continue
            health = await self.check_health(db, integration.id)
            if health is not None:
                results.append(health)
        return results
