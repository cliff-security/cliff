"""Integration registry — catalog of available integrations with setup guides.

Builtin entries are stored as JSON files in this directory. The registry is
loaded once at import time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_REGISTRY_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CredentialField(BaseModel):
    """Schema for a single credential field in an integration's setup form."""

    key_name: str
    label: str
    type: str = "password"  # "password", "text", "url"
    required: bool = True
    help_text: str | None = None
    placeholder: str | None = None


class RegistryEntry(BaseModel):
    """A single integration in the catalog."""

    id: str
    name: str
    adapter_type: str  # "finding_source", "ticketing", "ownership_context", "validation"
    description: str
    icon: str = "extension"  # Material Symbols icon name
    status: str = "coming_soon"  # "available", "coming_soon", "community"
    setup_guide_md: str = ""
    credentials_schema: list[CredentialField] = []
    config_fields: list[CredentialField] = []  # non-secret fields stored in integration config
    capabilities: list[str] = []  # "collect", "enrich", "investigate", "update"
    docs_url: str | None = None
    mcp_config: dict | None = None  # MCP server config template (Phase I-1)
    toolsets: dict[str, list[str]] | None = None  # action_tier -> toolset names
    default_action_tier: int = 0  # 0=read-only, 1=enrichment, 2=mutation

    # ADR-0035 / IMPL-0010 — set by the registry endpoint at request time
    # for the github entry, when the GitHub App + Device Flow onboarding
    # surface is available (env ``CLIFF_GITHUB_APP_CLIENT_ID`` is set).
    # Stays ``False`` for every other entry.
    github_app_available: bool = False

    # ADR-0048 — the "Install or manage the Cliff GitHub App" URL
    # (``github.com/apps/<slug>/installations/new``). Set alongside
    # ``github_app_available`` for the github entry; the Settings UI
    # renders it as an always-available affordance so a user can install
    # the App on the right repo regardless of onboarding state. ``None``
    # for every other entry.
    github_app_install_url: str | None = None


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------


def _load_entries() -> list[RegistryEntry]:
    """Load all JSON registry entries from the builtin registry directory."""
    entries: list[RegistryEntry] = []
    for path in sorted(_REGISTRY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            entries.append(RegistryEntry(**data))
        except Exception:
            logger.warning("Failed to load registry entry %s", path.name, exc_info=True)
    return entries


REGISTRY: list[RegistryEntry] = _load_entries()


def load_registry() -> list[RegistryEntry]:
    """Return all registry entries."""
    return REGISTRY


def get_registry_entry(entry_id: str) -> RegistryEntry | None:
    """Look up a single registry entry by ID."""
    for entry in REGISTRY:
        if entry.id == entry_id:
            return entry
    return None
