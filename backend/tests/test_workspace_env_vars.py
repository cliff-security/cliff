"""Tests for _resolve_repo_env_vars helper in workspace routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cliff.api.routes.workspaces import _resolve_repo_env_vars
from cliff.models import IntegrationConfig, Workspace


def _github_integration(
    *,
    repo_url: str | None = None,
    enabled: bool = True,
) -> IntegrationConfig:
    config = {"repo_url": repo_url} if repo_url else None
    return IntegrationConfig(
        id="int-gh-123",
        adapter_type="finding_source",
        provider_name="GitHub",
        enabled=enabled,
        config=config,
        action_tier=0,
        updated_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def mock_request():
    """Create a mock FastAPI Request with optional vault."""
    req = MagicMock()
    req.app.state.vault = None
    return req


@pytest.fixture
def mock_db():
    """Create a mock aiosqlite connection."""
    return AsyncMock()


async def test_resolve_both_url_and_token(mock_request, mock_db):
    """When GitHub integration has URL and vault has PAT, return full dict."""
    vault = AsyncMock()
    vault.retrieve = AsyncMock(return_value="ghp_realtoken")
    mock_request.app.state.vault = vault

    gh = _github_integration(repo_url="https://github.com/org/repo")

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[gh]),
    ):
        result = await _resolve_repo_env_vars(mock_request, mock_db)

    assert result == {
        "CLIFF_REPO_URL": "https://github.com/org/repo",
        "GH_TOKEN": "ghp_realtoken",
    }
    vault.retrieve.assert_awaited_once_with(
        "int-gh-123", "github_personal_access_token",
    )


async def test_resolve_url_only(mock_request, mock_db):
    """When GitHub integration has URL but no vault, return partial dict."""
    gh = _github_integration(repo_url="https://github.com/org/repo")

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[gh]),
    ):
        result = await _resolve_repo_env_vars(mock_request, mock_db)

    assert result == {"CLIFF_REPO_URL": "https://github.com/org/repo"}
    assert "GH_TOKEN" not in result


async def test_resolve_neither(mock_request, mock_db):
    """When no GitHub integration exists, return empty dict."""
    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[]),
    ):
        result = await _resolve_repo_env_vars(mock_request, mock_db)

    assert result == {}


async def test_resolve_vault_none(mock_request, mock_db):
    """When vault is None, only URL is returned (no GH_TOKEN)."""
    gh = _github_integration(repo_url="https://github.com/x/y")
    mock_request.app.state.vault = None

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[gh]),
    ):
        result = await _resolve_repo_env_vars(mock_request, mock_db)

    assert result == {"CLIFF_REPO_URL": "https://github.com/x/y"}
    assert "GH_TOKEN" not in result


# ---------------------------------------------------------------------------
# Workspace repo snapshot (migration 013)
# ---------------------------------------------------------------------------


def _ws(*, repo_url: str | None) -> Workspace:
    now = datetime.now(UTC)
    return Workspace(
        id="ws-1",
        finding_id="f-1",
        state="open",
        repo_url=repo_url,
        created_at=now,
        updated_at=now,
    )


async def test_snapshot_url_wins_over_integration(mock_request, mock_db):
    """Workspace.repo_url is preferred over the live integration value.

    This is the multi-repo-PAT safety net: if the user changes the
    integration repo from A to B while a workspace opened against A is in
    flight, the workspace must keep operating on A.
    """
    gh = _github_integration(repo_url="https://github.com/org/B")
    workspace = _ws(repo_url="https://github.com/org/A")

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[gh]),
    ):
        result = await _resolve_repo_env_vars(
            mock_request, mock_db, workspace=workspace
        )

    assert result["CLIFF_REPO_URL"] == "https://github.com/org/A"


async def test_no_snapshot_falls_back_to_integration(mock_request, mock_db):
    """Pre-migration workspaces (repo_url=None) fall back to the integration."""
    gh = _github_integration(repo_url="https://github.com/org/legacy")
    workspace = _ws(repo_url=None)

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[gh]),
    ):
        result = await _resolve_repo_env_vars(
            mock_request, mock_db, workspace=workspace
        )

    assert result["CLIFF_REPO_URL"] == "https://github.com/org/legacy"


async def test_snapshot_works_without_integration(mock_request, mock_db):
    """If the integration was deleted, the snapshot still drives the URL.

    Token-less, but the URL is enough for read-only operations and for
    error messages downstream.
    """
    workspace = _ws(repo_url="https://github.com/org/snapshotted")

    with patch(
        "cliff.api.routes.workspaces.list_integrations",
        new=AsyncMock(return_value=[]),
    ):
        result = await _resolve_repo_env_vars(
            mock_request, mock_db, workspace=workspace
        )

    assert result == {"CLIFF_REPO_URL": "https://github.com/org/snapshotted"}
