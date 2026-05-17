"""Verify the GitHub token lookup helpers find the right vault entry
regardless of which onboarding path created the integration row.

Regression test for the alignment bug where the device-flow path stored
``adapter_type='finding_source'`` / ``provider_name='github'`` while the
PAT path used ``adapter_type='github'`` / ``provider_name='GitHub'`` — a
mismatch that silently made every assessment + workspace clone run
unauthenticated for App-flow users.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cliff.db import repo_integration
from cliff.db.connection import close_db, init_db
from cliff.integrations.vault import CredentialVault
from cliff.models import IntegrationConfigCreate

VAULT_KEY = b"\x00" * 32


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def _seed_github_integration(
    db,
    *,
    adapter_type: str,
    provider_name: str,
    enabled: bool,
    token: str | None = "ghu_appflow_token_value",
) -> str:
    integ = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type=adapter_type,
            provider_name=provider_name,
            enabled=enabled,
            config={"repo_url": "https://github.com/owner/repo"},
            action_tier=0,
        ),
    )
    if token is not None:
        vault = CredentialVault(db, key=VAULT_KEY)
        await vault.store(integ.id, "github_personal_access_token", token)
    return integ.id


# ---------------------------------------------------------------------------
# _github_token_from_integration (used by assessment engine + spawner)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_lookup_resolves_pat_row_with_capitalized_provider(db):
    """The legacy PAT onboarding writes provider_name='GitHub' (capital G).
    The lookup must find this row."""
    await _seed_github_integration(
        db, adapter_type="github", provider_name="GitHub", enabled=True
    )

    from cliff.api import _engine_dep
    from cliff.main import app

    vault = CredentialVault(db, key=VAULT_KEY)
    app.state.vault = vault
    try:
        with patch("cliff.db.connection._db", db):
            token = await _engine_dep._github_token_from_integration()
    finally:
        app.state.vault = None
    assert token == "ghu_appflow_token_value"


@pytest.mark.asyncio
async def test_token_lookup_resolves_app_flow_row_with_lowercase_provider(db):
    """A legacy lowercase device-flow row (from before the alignment fix)
    must still resolve via case-insensitive lookup."""
    await _seed_github_integration(
        db,
        adapter_type="finding_source",
        provider_name="github",
        enabled=True,
    )

    from cliff.api import _engine_dep
    from cliff.main import app

    vault = CredentialVault(db, key=VAULT_KEY)
    app.state.vault = vault
    try:
        with patch("cliff.db.connection._db", db):
            token = await _engine_dep._github_token_from_integration()
    finally:
        app.state.vault = None
    assert token == "ghu_appflow_token_value"


@pytest.mark.asyncio
async def test_token_lookup_returns_none_when_no_enabled_row(db):
    await _seed_github_integration(
        db, adapter_type="github", provider_name="GitHub", enabled=False
    )

    from cliff.api import _engine_dep
    from cliff.main import app

    vault = CredentialVault(db, key=VAULT_KEY)
    app.state.vault = vault
    try:
        with patch("cliff.db.connection._db", db):
            token = await _engine_dep._github_token_from_integration()
    finally:
        app.state.vault = None
    assert token is None


@pytest.mark.asyncio
async def test_token_lookup_picks_enabled_row_when_pat_archived(db):
    """After App connect archives the PAT row (enabled=False), the lookup
    must skip the PAT row and return the App-flow token."""
    # Disabled PAT row first, with a token still in the vault under it.
    await _seed_github_integration(
        db,
        adapter_type="github",
        provider_name="GitHub",
        enabled=False,
        token="ghp_archived_pat",
    )
    # Active App-flow row with the user access token.
    await _seed_github_integration(
        db,
        adapter_type="github",
        provider_name="GitHub",
        enabled=True,
        token="ghu_active_app_token",
    )

    from cliff.api import _engine_dep
    from cliff.main import app

    vault = CredentialVault(db, key=VAULT_KEY)
    app.state.vault = vault
    try:
        with patch("cliff.db.connection._db", db):
            token = await _engine_dep._github_token_from_integration()
    finally:
        app.state.vault = None
    assert token == "ghu_active_app_token"
