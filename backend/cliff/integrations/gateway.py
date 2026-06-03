"""MCP Gateway — config generator for workspace MCP server integration (ADR-0018).

The gateway resolves which integrations are enabled, decrypts their credentials
from the vault, substitutes ``${credential:key_name}`` placeholders in MCP
config templates, and returns the resolved configs. Pydantic AI consumes them
as MCP toolsets via the adapter in ``cliff.agents.runtime.tools.mcp``; the
gateway's job is purely **config generation**.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cliff.db.repo_integration import list_integrations
from cliff.integrations.audit import AuditEvent
from cliff.integrations.registry import RegistryEntry, get_registry_entry

if TYPE_CHECKING:
    import aiosqlite

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\$\{credential:([a-zA-Z0-9_]+)\}")


@dataclass
class ResolvedWorkspaceIntegration:
    """Metadata about a resolved integration for the workspace manifest."""

    integration_id: str
    provider_name: str
    registry_id: str
    action_tier: int = 0
    capabilities: list[str] = field(default_factory=list)
    status: str = "connected"


@dataclass
class WorkspaceMCPResult:
    """Result of resolving MCP configs for a workspace."""

    mcp_configs: dict[str, dict[str, Any]]
    integrations: list[ResolvedWorkspaceIntegration]


@dataclass
class ConfigFreshnessResult:
    """Result of checking whether a workspace's MCP config is stale."""

    stale: bool = False
    reason: str = ""


class MCPConfigResolver:
    """Resolves MCP server configurations for the workspace's PA MCP toolsets."""

    def __init__(
        self,
        vault: CredentialVault,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._vault = vault
        self._audit = audit_logger

    async def resolve_workspace_mcp_configs(
        self, db: aiosqlite.Connection
    ) -> dict[str, dict[str, Any]]:
        """Resolve MCP configs for all enabled integrations.

        Returns a dict mapping integration registry ID -> resolved MCP config.
        Convenience wrapper around :meth:`resolve_workspace` for backward compat.
        """
        result = await self.resolve_workspace(db)
        return result.mcp_configs

    async def resolve_workspace(
        self, db: aiosqlite.Connection
    ) -> WorkspaceMCPResult:
        """Resolve MCP configs and integration metadata for a workspace.

        Returns :class:`WorkspaceMCPResult` with both the MCP config dict
        (for the PA MCP toolset adapter) and integration metadata list (for
        the ``workspace-integrations.json`` manifest).

        Only includes integrations that have:
        1. An entry in ``integration_config`` with ``enabled=True``
        2. A registry entry with non-null ``mcp_config``
        3. All required credentials stored in the vault

        Integrations that fail any check are silently skipped with a log warning.
        """
        integrations = await list_integrations(db)
        mcp_configs: dict[str, dict[str, Any]] = {}
        ws_integrations: list[ResolvedWorkspaceIntegration] = []

        for integration in integrations:
            if not integration.enabled:
                continue

            # Look up registry entry for MCP config template.
            registry_id = integration.provider_name.lower().replace(" ", "-")
            entry = get_registry_entry(registry_id)
            if entry is None or entry.mcp_config is None:
                logger.debug(
                    "Skipping integration %s (%s): no MCP config in registry",
                    integration.id,
                    integration.provider_name,
                )
                continue

            # Decrypt credentials.
            try:
                credentials = await self._vault.get_credentials_for_workspace(
                    integration.id
                )
            except Exception:
                logger.warning(
                    "Skipping integration %s (%s): failed to decrypt credentials",
                    integration.id,
                    integration.provider_name,
                    exc_info=True,
                )
                continue

            if not credentials:
                logger.warning(
                    "Skipping integration %s (%s): no credentials stored",
                    integration.id,
                    integration.provider_name,
                )
                continue

            # Resolve placeholders.
            resolved = self.resolve_placeholders(entry.mcp_config, credentials)

            # Check for unresolved placeholders.
            unresolved = _find_unresolved_placeholders(resolved)
            if unresolved:
                logger.warning(
                    "Skipping integration %s (%s): unresolved placeholders: %s",
                    integration.id,
                    integration.provider_name,
                    unresolved,
                )
                continue

            # Apply toolset scoping and read-only adjustments based on action tier.
            _apply_toolset_scoping(resolved, entry, integration.action_tier)

            mcp_configs[entry.id] = resolved
            ws_integrations.append(
                ResolvedWorkspaceIntegration(
                    integration_id=integration.id,
                    provider_name=integration.provider_name,
                    registry_id=entry.id,
                    action_tier=integration.action_tier,
                    capabilities=entry.capabilities,
                )
            )

            # Emit audit event.
            if self._audit is not None:
                await self._audit.log(
                    AuditEvent(
                        event_type="mcp.config_resolved",
                        integration_id=integration.id,
                        provider_name=integration.provider_name,
                        status="success",
                    )
                )
            logger.info(
                "Resolved MCP config for %s (integration %s)",
                entry.id,
                integration.id,
            )

        return WorkspaceMCPResult(mcp_configs=mcp_configs, integrations=ws_integrations)

    async def check_config_freshness(
        self,
        db: aiosqlite.Connection,
        workspace_dir: str | Path,
    ) -> ConfigFreshnessResult:
        """Check if a workspace's MCP config is stale.

        Compares the workspace's ``workspace-integrations.json`` manifest
        against the current state of integrations and credentials.

        Returns a :class:`ConfigFreshnessResult` indicating whether the
        config needs regeneration (workspace restart required).
        """
        workspace_path = Path(workspace_dir)
        manifest_path = workspace_path / "workspace-integrations.json"

        # No manifest = no integrations were configured at creation time.
        if not manifest_path.exists():
            # Check if there are now integrations that should be there.
            current = await self.resolve_workspace(db)
            if current.mcp_configs:
                return ConfigFreshnessResult(
                    stale=True,
                    reason="New integrations available since workspace was created",
                )
            return ConfigFreshnessResult(stale=False)

        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            return ConfigFreshnessResult(stale=True, reason="Manifest unreadable")

        manifest_ids = {entry["integration_id"] for entry in manifest}

        # Resolve current state.
        current = await self.resolve_workspace(db)
        current_ids = {i.integration_id for i in current.integrations}

        # Check for added/removed integrations.
        added = current_ids - manifest_ids
        removed = manifest_ids - current_ids

        if added:
            return ConfigFreshnessResult(
                stale=True,
                reason=f"New integrations added: {added}",
            )
        if removed:
            return ConfigFreshnessResult(
                stale=True,
                reason=f"Integrations removed or disabled: {removed}",
            )

        # Check for tier changes.
        manifest_tiers = {e["integration_id"]: e.get("action_tier", 0) for e in manifest}
        for ci in current.integrations:
            if manifest_tiers.get(ci.integration_id) != ci.action_tier:
                return ConfigFreshnessResult(
                    stale=True,
                    reason=f"Action tier changed for {ci.provider_name}",
                )

        return ConfigFreshnessResult(stale=False)

    @staticmethod
    def resolve_placeholders(
        mcp_config: dict[str, Any], credentials: dict[str, str]
    ) -> dict[str, Any]:
        """Replace ``${credential:key_name}`` placeholders with real values.

        Only substitutes within the ``env`` dict values. The ``command`` and
        ``args`` fields are preserved unchanged. Returns a deep copy — the
        original template is never mutated.
        """
        resolved = copy.deepcopy(mcp_config)
        # Support both "environment" (stdio MCP format) and "env" (legacy).
        # Explicit-key precedence: an explicit (even empty) "environment" wins
        # over the legacy "env", so an empty ``environment: {}`` isn't silently
        # treated as missing and a config carrying both can't substitute into
        # the wrong field.
        env = (
            resolved["environment"]
            if "environment" in resolved
            else resolved.get("env")
        )
        if not isinstance(env, dict):
            return resolved

        for key, value in env.items():
            if not isinstance(value, str):
                continue
            env[key] = _PLACEHOLDER_RE.sub(
                lambda m: credentials.get(m.group(1), m.group(0)),
                value,
            )

        return resolved


def _apply_toolset_scoping(
    config: dict[str, Any],
    entry: RegistryEntry,
    action_tier: int,
) -> None:
    """Mutate *config* in-place to apply toolset scoping and read-only rules.

    - If the registry entry defines ``toolsets``, append ``--toolsets <list>``
      to the resolved ``command`` array for the given *action_tier*.
    - If *action_tier* > 0, remove ``--read-only`` from ``command`` (user
      opted into writes).

    Works with both legacy format (separate ``args`` key) and the stdio MCP
    format (``command`` is the full argument array).
    """
    # Support both formats: "command" (array) or legacy "args" (array).
    if isinstance(config.get("command"), list):
        key = "command"
    elif isinstance(config.get("args"), list):
        key = "args"
    else:
        return

    cmd = config[key]

    # Toolset scoping: append --toolsets flag if the entry defines them.
    if entry.toolsets:
        tier_key = str(action_tier)
        toolset_list = entry.toolsets.get(tier_key)
        if toolset_list:
            config[key] = [a for a in cmd if a != "--toolsets"] + [
                "--toolsets",
                ",".join(toolset_list),
            ]
            cmd = config[key]

    # Read-only removal: if user opted into higher tier, remove --read-only.
    if action_tier > 0 and "--read-only" in cmd:
        config[key] = [a for a in cmd if a != "--read-only"]


def _find_unresolved_placeholders(config: dict[str, Any]) -> list[str]:
    """Return any ``${credential:...}`` placeholders still present in env values."""
    # Same explicit-key precedence as ``_resolve_credentials`` above.
    env = config["environment"] if "environment" in config else config.get("env")
    if not isinstance(env, dict):
        return []
    unresolved = []
    for value in env.values():
        if isinstance(value, str):
            unresolved.extend(_PLACEHOLDER_RE.findall(value))
    return unresolved
